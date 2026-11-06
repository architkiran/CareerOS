import json
from pathlib import Path
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from careeros.db.models import Application, Company, Document, Job, RoleLane
from careeros.modules.agents import service as agents
from careeros.modules.applications import service as apps
from careeros.modules.approvals import service as gate
from careeros.modules.documents import service as docs
from careeros.modules.outreach import service as outreach
from careeros.modules.system.status import get_system_status
from careeros.web import forms
from careeros.web.csrf import verify_csrf
from careeros.web.deps import get_session

router = APIRouter(dependencies=[Depends(verify_csrf)])
SessionDep = Annotated[Session, Depends(get_session)]


def _render(
    request: Request, template: str, ctx: dict[str, Any], status_code: int = 200
) -> HTMLResponse:
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request, template, ctx, status_code=status_code
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def workspace_ctx(session: Session, app: Application) -> dict[str, Any]:
    job = session.get(Job, app.job_id)
    assert job is not None
    company = session.get(Company, job.company_id)
    lane = session.get(RoleLane, app.role_lane_id) if app.role_lane_id else None
    ds = docs.documents_for(session, app.id)
    current = [d for d in (ds.resume, ds.cover_letter) if d is not None]
    return {
        "a": app,
        "job": job,
        "company": company,
        "lane": lane,
        "docs": ds,
        "claims": {d.id: docs.claims_for(session, d.id) for d in current},
        "findings": {d.id: docs.findings(d) for d in current},
        "tailoring": {
            d.id: json.loads(docs.load_content(d).context.get("tailoring", "{}"))
            for d in current
            if docs.integrity_error(d) is None
        },
        "integrity_errors": {d.id: docs.integrity_error(d) for d in current},
        "history": apps.history(session, app.id),
        "next_statuses": apps.TRANSITIONS[app.status],
        "labels": docs.DOC_LABELS,
        "drafts": [
            (d, c, outreach.read_body(d))
            for d, c in outreach.drafts_for_application(session, app.id)
        ],
        "follow_ups": [
            f for f in gate.open_follow_ups(session) if f.follow_up.application_id == app.id
        ],
        "approvals": [a for a in gate.list_approvals(session) if a.target_id == app.id],
    }


def _workspace(
    request: Request,
    session: Session,
    app_id: str,
    extra: dict[str, Any] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    app = session.get(Application, app_id)
    if app is None:
        raise HTTPException(404, "Application not found")
    return _render(
        request, "application.html", workspace_ctx(session, app) | (extra or {}), status_code
    )


@router.get("/applications", response_class=HTMLResponse)
def list_page(request: Request, session: SessionDep, status: str | None = None) -> HTMLResponse:
    if status not in (None, "", *apps.STATUSES):
        status = None
    rows = apps.list_applications(session, status or None)
    return _render(
        request, "applications.html", {"rows": rows, "status": status, "statuses": apps.STATUSES}
    )


@router.post("/jobs/{job_id}/application")
def start(job_id: str, session: SessionDep) -> Response:
    try:
        app = apps.start_application(session, job_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    agents.start_support_mission(session, app.id, "evidence")
    agents.start_support_mission(session, app.id, "networking")
    session.commit()
    return RedirectResponse(f"/applications/{app.id}", status_code=303)


@router.get("/applications/{app_id}", response_class=HTMLResponse)
def workspace(app_id: str, request: Request, session: SessionDep) -> HTMLResponse:
    return _workspace(request, session, app_id)


@router.post("/applications/{app_id}/prepare")
def prepare(app_id: str, request: Request, session: SessionDep) -> Response:
    if not get_system_status(
        request.app.state.settings, request.app.state.engine
    ).schema.up_to_date:
        raise HTTPException(409, "Run careeros migrate before starting draft preparation.")
    try:
        mission, _ = agents.start_application_mission(session, app_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except agents.MissionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return RedirectResponse(f"/missions/{mission.id}", status_code=303)


def _sync(session: Session, app_id: str) -> None:
    app = session.get(Application, app_id)
    resume = docs.latest(session, app_id, "resume")
    if app is not None:
        apps.sync_ready(
            session,
            app,
            resume is not None
            and resume.status == "ready"
            and docs.integrity_error(resume) is None,
        )


@router.post("/applications/{app_id}/resume-pdf")
async def generate_pdf(app_id: str, request: Request, session: SessionDep) -> Response:
    form = await request.form()
    try:
        docs.generate(
            session,
            app_id,
            "resume",
            Path(request.app.state.settings.data_dir),
            render_format="pdf",
            project_limit=int(forms.text(form, "project_limit") or "4"),
            experience_limit=int(forms.text(form, "experience_limit") or "20"),
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (docs.DocumentError, ValueError) as exc:
        session.rollback()
        return _workspace(request, session, app_id, {"errors": [str(exc)]}, 422)
    _sync(session, app_id)
    session.commit()
    return RedirectResponse(f"/applications/{app_id}#documents", status_code=303)


@router.post("/applications/{app_id}/documents")
async def generate(app_id: str, request: Request, session: SessionDep) -> Response:
    f = await request.form()
    doc_type = forms.text(f, "document_type") or ""
    if doc_type not in docs.DOC_LABELS:
        raise HTTPException(422, "Unknown document type")
    try:
        docs.generate(
            session,
            app_id,
            cast(docs.DocType, doc_type),
            Path(request.app.state.settings.data_dir),
            render_format="pdf" if doc_type == "resume" else "docx",
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except docs.DocumentError as exc:
        session.rollback()
        return _workspace(request, session, app_id, {"errors": [str(exc)]}, 422)
    _sync(session, app_id)
    session.commit()
    return RedirectResponse(f"/applications/{app_id}#documents", status_code=303)


@router.post("/documents/{doc_id}/acknowledge")
def acknowledge(doc_id: str, request: Request, session: SessionDep) -> Response:
    try:
        doc = docs.acknowledge(session, doc_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except docs.DocumentError as exc:
        session.rollback()
        d = session.get(Document, doc_id)
        assert d is not None
        return _workspace(request, session, d.application_id, {"errors": [str(exc)]}, 422)
    _sync(session, doc.application_id)
    session.commit()
    return RedirectResponse(f"/applications/{doc.application_id}#documents", status_code=303)


def _doc_file(request: Request, doc: Document) -> Path:
    root = (Path(request.app.state.settings.data_dir) / "documents").resolve()
    path = Path(doc.storage_path).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "Document file not found")
    return path


@router.get("/documents/{doc_id}/download")
def download(
    doc_id: str, request: Request, session: SessionDep, inline: bool = False
) -> FileResponse:
    doc = session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    path = _doc_file(request, doc)
    try:
        docs.verify_integrity(doc)
    except (docs.DocumentError, OSError) as exc:
        raise HTTPException(409, "Stored document failed its integrity check.") from exc
    return FileResponse(
        path,
        filename=("Archit_Kiran_Kumar_Resume" if doc.document_type == "resume" else "Cover_Letter")
        + path.suffix,
        media_type="application/pdf"
        if path.suffix == ".pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content_disposition_type="inline" if inline and path.suffix == ".pdf" else "attachment",
        headers={
            "Cache-Control": "no-store",
            **(
                {
                    "X-Frame-Options": "SAMEORIGIN",
                    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'self'",
                }
                if inline and path.suffix == ".pdf"
                else {}
            ),
        },
    )


@router.get("/documents/{doc_id}/diff", response_class=HTMLResponse)
def diff_page(doc_id: str, request: Request, session: SessionDep) -> HTMLResponse:
    try:
        prev, lines = docs.diff(session, doc_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (docs.DocumentError, OSError) as exc:
        raise HTTPException(409, "Stored document failed its integrity check.") from exc
    doc = session.get(Document, doc_id)
    return _render(
        request,
        "document_diff.html",
        {"doc": doc, "prev": prev, "lines": lines, "labels": docs.DOC_LABELS},
    )


@router.post("/applications/{app_id}/status")
async def change_status(app_id: str, request: Request, session: SessionDep) -> Response:
    f = await request.form()
    try:
        apps.set_status(session, app_id, forms.text(f, "status") or "", forms.text(f, "notes"))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except apps.ApplicationError as exc:
        session.rollback()
        return _workspace(request, session, app_id, {"errors": [str(exc)]}, 422)
    session.commit()
    return RedirectResponse(f"/applications/{app_id}", status_code=303)


@router.post("/applications/{app_id}/notes")
async def save_notes(app_id: str, request: Request, session: SessionDep) -> Response:
    f = await request.form()
    app = session.get(Application, app_id)
    if app is None:
        raise HTTPException(404, "Application not found")
    app.notes = (forms.text(f, "notes") or "")[:5000] or None
    session.commit()
    return RedirectResponse(f"/applications/{app_id}", status_code=303)


@router.post("/applications/{app_id}/networking")
def prepare_networking(app_id: str, session: SessionDep) -> Response:
    try:
        agents.start_support_mission(session, app_id, "networking")
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    return RedirectResponse(f"/applications/{app_id}/workbench#people", 303)


@router.get("/documents/{doc_id}/preview")
def document_preview(doc_id: str, request: Request, session: SessionDep) -> FileResponse:
    from careeros.modules.documents.preview import preview_path

    document = session.get(Document, doc_id)
    if document is None:
        raise HTTPException(404, "Document not found")
    _doc_file(request, document)
    try:
        path = preview_path(document)
    except docs.DocumentError as exc:
        raise HTTPException(409, str(exc)) from exc
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})
