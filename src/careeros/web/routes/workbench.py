import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.common.fs import private_dir
from careeros.db.models import Application, Company, Job
from careeros.modules.agents.support import evidence, load_report
from careeros.modules.applications.service import sync_ready
from careeros.modules.documents import service as docs
from careeros.modules.documents.content import build_resume, experience_paragraphs
from careeros.modules.documents.tailoring import plan
from careeros.modules.documents.workbench import Choices, inventory, recommended_skills
from careeros.modules.profile import service as profiles
from careeros.modules.system.settings_store import get_setting
from careeros.web.csrf import verify_csrf
from careeros.web.deps import get_session

router = APIRouter(dependencies=[Depends(verify_csrf)])
SessionDep = Annotated[Session, Depends(get_session)]


def context(session: Session, app_id: str, data_dir: Path) -> dict[str, Any]:
    app = session.get(Application, app_id)
    if app is None:
        raise HTTPException(404, "Application not found")
    job = session.get(Job, app.job_id)
    assert job
    candidate = docs.load_candidate(session)
    ranked = plan(candidate, job.title, job.description_text)
    content = build_resume(candidate, job.title, "", job.description_text, "")
    current = docs.latest(session, app_id, "resume")
    # Older sparse drafts are still previewable; the editable baseline now comes
    # from complete master-backed evidence rather than inheriting their losses.
    if current and docs.integrity_error(current) is None:
        saved = docs.load_content(current)
        if saved.context.get("editor") == "evidence-workbench-v1":
            content = saved
    selected = {ref for c in content.claims() for ref in c.refs}
    selections = Choices(
        project_refs=[
            p.ref for p in candidate.projects if p.ref in selected and p.ref in ranked.source_refs
        ],
        experience_refs=[e.ref for e in candidate.experience],
        skills=recommended_skills(
            candidate,
            [ref for ref in ranked.source_refs if ref.startswith("project:")],
            job.title + " " + job.description_text,
        ),
        summary="\n".join(
            c.text for name, claims in content.sections if name == "Summary" for c in claims
        ),
        experience_edits={},
    )
    # Recover exact saved editor choices instead of silently reselecting exclusions.
    if content.context.get("choices"):
        selections = Choices.model_validate_json(content.context["choices"])
    else:
        selections.experience_edits = {
            e.ref: "\n".join(experience_paragraphs(e.text.split("|", 2)[-1]))
            for e in candidate.experience
        }
    feedback_path = data_dir / "documents" / app_id / "feedback.json"
    return {
        "a": app,
        "job": job,
        "company": session.get(Company, job.company_id),
        "candidate": candidate,
        "pending_projects": [
            p
            for p in profiles.list_projects(session, profiles.get_or_create_profile(session).id)
            if p.verified_status != "verified"
        ],
        "choices": selections,
        "projects": inventory(candidate, job.title + " " + job.description_text),
        "evidence": evidence(session, app_id),
        "networking": load_report(data_dir, app_id, "networking"),
        "current": current,
        "master": get_setting(session, "resume.master", {}),
        "original_summary": next(
            (f.text for f in candidate.other_facts if f.kind == "master_summary"), ""
        ),
        "feedback_history": json.loads(feedback_path.read_text())
        if feedback_path.is_file()
        else [],
    }


def render(
    request: Request,
    session: Session,
    app_id: str,
    extra: dict[str, Any] | None = None,
    status: int = 200,
) -> HTMLResponse:
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request,
        "workbench.html",
        context(session, app_id, Path(request.app.state.settings.data_dir)) | (extra or {}),
        status_code=status,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/applications/{app_id}/workbench")
def page(app_id: str, request: Request, session: SessionDep) -> HTMLResponse:
    return render(request, session, app_id)


@router.post("/applications/{app_id}/workbench")
async def revise(app_id: str, request: Request, session: SessionDep) -> Response:
    form = await request.form()
    candidate = docs.load_candidate(session)
    try:
        chosen = Choices(
            project_refs=[str(x) for x in form.getlist("projects")],
            experience_refs=[str(x) for x in form.getlist("experiences")],
            skills=[str(x) for x in form.getlist("skills")],
            summary=str(form.get("summary", "")),
            feedback=str(form.get("feedback", "")),
            experience_edits={
                e.ref: str(form.get("edit-" + e.ref, ""))
                for e in candidate.experience
                if e.ref in form.getlist("experiences")
            },
        )
    except ValidationError as exc:
        raise HTTPException(422, "Resume choices exceed supported limits.") from exc
    app = session.get(Application, app_id)
    if app is None:
        raise HTTPException(404, "Application not found")
    if app.status not in ("preparing", "ready"):
        raise HTTPException(409, "This application has moved beyond draft preparation.")
    latest = docs.latest(session, app_id, "resume")
    if str(form.get("base_version", "0")) != str(latest.version if latest else 0):
        return render(
            request,
            session,
            app_id,
            {
                "errors": [
                    "A newer version exists. Reload before saving; "
                    "your current edits are shown below."
                ],
                "choices": chosen,
            },
            409,
        )
    folder = Path(request.app.state.settings.data_dir) / "documents" / app_id
    private_dir(folder)
    history_path = folder / "feedback.json"
    if str(form.get("intent", "")) == "feedback":
        history = json.loads(history_path.read_text()) if history_path.is_file() else []
        history.append(
            {
                "text": chosen.feedback,
                "at": utcnow().isoformat(),
                "status": "Saved request; apply changes in the editor "
                "before generating a revision.",
            }
        )
        history_path.write_text(json.dumps(history[-50:]))
        history_path.chmod(0o600)
        return render(
            request,
            session,
            app_id,
            {"choices": chosen, "notice": "Feedback saved. Your resume has not been changed."},
        )
    try:
        doc = docs.generate(
            session,
            app_id,
            "resume",
            Path(request.app.state.settings.data_dir),
            render_format="pdf",
            choices=chosen,
        )
        sync_ready(session, app, doc.status == "ready")
        session.commit()
    except (docs.DocumentError, ValueError) as exc:
        session.rollback()
        return render(request, session, app_id, {"errors": [str(exc)], "choices": chosen}, 422)
    return RedirectResponse(f"/applications/{app_id}/workbench?saved=1", 303)
