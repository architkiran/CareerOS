from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from careeros.db.models import Application, Approval, Document, Job, OutreachDraft
from careeros.modules.approvals import service as gate
from careeros.modules.outreach import service as outreach
from careeros.web import forms
from careeros.web.csrf import verify_csrf
from careeros.web.deps import error_messages, get_session

router = APIRouter(dependencies=[Depends(verify_csrf)])
SessionDep = Annotated[Session, Depends(get_session)]


def _render(
    request: Request, template: str, ctx: dict[str, Any], status_code: int = 200
) -> HTMLResponse:
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request, template, ctx, status_code=status_code
    )
    return response


def _data_dir(request: Request) -> Path:
    return Path(request.app.state.settings.data_dir)


def _app_error(request: Request, session: Session, app_id: str, errors: list[str]) -> HTMLResponse:
    from careeros.web.routes.applications import workspace_ctx

    session.rollback()
    app = session.get(Application, app_id)
    if app is None:
        raise HTTPException(404, "Application not found")
    return _render(
        request, "application.html", workspace_ctx(session, app) | {"errors": errors}, 422
    )


@router.get("/approvals", response_class=HTMLResponse)
def approvals_page(request: Request, session: SessionDep) -> HTMLResponse:
    rows = gate.list_approvals(session)
    session.commit()  # persist any expirations/invalidations found while listing
    return _render(
        request,
        "approvals.html",
        {
            "pending": [a for a in rows if a.status in ("pending", "approved")],
            "history": [a for a in rows if a.status not in ("pending", "approved")],
            "labels": gate.ACTION_LABELS,
        },
    )


@router.post("/applications/{app_id}/approval")
async def request_submission(app_id: str, request: Request, session: SessionDep) -> Response:
    f = await request.form()
    try:
        payload = gate.application_payload(
            session, app_id, forms.checkbox(f, "include_cover_letter")
        )
        approval = gate.request(session, payload, _data_dir(request))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except gate.ApprovalError as exc:
        return _app_error(request, session, app_id, [str(exc)])
    session.commit()
    return RedirectResponse(f"/approvals/{approval.id}", status_code=303)


@router.get("/approvals/{approval_id}", response_class=HTMLResponse)
def approval_page(approval_id: str, request: Request, session: SessionDep) -> HTMLResponse:
    approval = session.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(404, "Approval not found")
    gate.refresh(session, approval)
    session.commit()
    try:
        snap = gate.snapshot(approval)
        integrity_ok = True
    except (gate.ApprovalError, OSError):
        snap, integrity_ok = {"data": {}}, False
    ctx: dict[str, Any] = {
        "a": approval,
        "snap": snap,
        "integrity_ok": integrity_ok,
        "labels": gate.ACTION_LABELS,
    }
    if approval.action_type == "submit_application":
        app = session.get(Application, approval.target_id)
        ctx["application"] = app
        ctx["job"] = session.get(Job, app.job_id) if app else None
        ctx["documents"] = {
            d.content_hash: d
            for d in session.query(Document).filter(Document.application_id == approval.target_id)
        }
    else:
        draft = session.get(OutreachDraft, approval.target_id)
        ctx["draft"] = draft
        ctx["body"] = outreach.read_body(draft) if draft else ""
    return _render(request, "approval.html", ctx)


@router.post("/approvals/{approval_id}/decide")
async def decide(approval_id: str, request: Request, session: SessionDep) -> Response:
    f = await request.form()
    decision = forms.text(f, "decision")
    if decision not in ("approve", "reject"):
        raise HTTPException(422, "Unknown decision")
    try:
        gate.decide(
            session,
            approval_id,
            decision == "approve",
            confirmed=forms.checkbox(f, "confirmed"),
            note=forms.text(f, "note"),
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except gate.ApprovalError as exc:
        session.commit()  # keep any invalidation/expiry that was detected
        return RedirectResponse(f"/approvals/{approval_id}?error={_q(str(exc))}", status_code=303)
    session.commit()
    return RedirectResponse(f"/approvals/{approval_id}", status_code=303)


def _q(text: str) -> str:
    from urllib.parse import quote

    return quote(text[:200])


def _parse_local(value: str | None, tz: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo(tz)).astimezone(UTC)
    except ValueError:
        return None


@router.post("/approvals/{approval_id}/done")
async def done(approval_id: str, request: Request, session: SessionDep) -> Response:
    f = await request.form()
    when = _parse_local(forms.text(f, "when"), request.app.state.settings.display_timezone)
    try:
        gate.confirm_done(session, approval_id, confirmed=forms.checkbox(f, "confirmed"), when=when)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except gate.ApprovalError as exc:
        session.commit()
        return RedirectResponse(f"/approvals/{approval_id}?error={_q(str(exc))}", status_code=303)
    session.commit()
    return RedirectResponse(f"/approvals/{approval_id}", status_code=303)


# ---------- outreach ----------


@router.post("/applications/{app_id}/outreach")
async def new_draft(app_id: str, request: Request, session: SessionDep) -> Response:
    f = await request.form()
    app = session.get(Application, app_id)
    if app is None:
        raise HTTPException(404, "Application not found")
    job = session.get(Job, app.job_id)
    assert job is not None
    try:
        contact = outreach.add_contact(
            session,
            job.company_id,
            outreach.ContactIn(
                name=forms.text(f, "name") or "",
                role=forms.text(f, "role"),
                public_profile_url=forms.text(f, "public_profile_url"),
                source_url=forms.text(f, "source_url"),
            ),
        )
        outreach.save_draft(
            session,
            contact.id,
            outreach.DraftIn(
                channel=forms.text(f, "channel") or "",
                recipient=forms.text(f, "recipient") or "",
                subject=forms.text(f, "subject"),
                body=forms.text(f, "body") or "",
            ),
            _data_dir(request),
            application_id=app_id,
        )
    except ValidationError as exc:
        return _app_error(request, session, app_id, error_messages(exc))
    session.commit()
    return RedirectResponse(f"/applications/{app_id}#outreach", status_code=303)


@router.post("/outreach/{draft_id}/edit")
async def edit_draft(draft_id: str, request: Request, session: SessionDep) -> Response:
    f = await request.form()
    draft = session.get(OutreachDraft, draft_id)
    if draft is None:
        raise HTTPException(404, "Draft not found")
    try:
        outreach.save_draft(
            session,
            draft.contact_id,
            outreach.DraftIn(
                channel=forms.text(f, "channel") or draft.channel,
                recipient=forms.text(f, "recipient") or "",
                subject=forms.text(f, "subject"),
                body=forms.text(f, "body") or "",
            ),
            _data_dir(request),
            draft_id=draft_id,
        )
    except (ValidationError, ValueError) as exc:
        msgs = error_messages(exc) if isinstance(exc, ValidationError) else [str(exc)]
        if draft.application_id:
            return _app_error(request, session, draft.application_id, msgs)
        raise HTTPException(422, "; ".join(msgs)) from exc
    session.commit()
    return RedirectResponse(f"/applications/{draft.application_id}#outreach", status_code=303)


@router.post("/outreach/{draft_id}/approval")
def request_outreach(draft_id: str, request: Request, session: SessionDep) -> Response:
    try:
        approval = gate.request(
            session, gate.outreach_payload(session, draft_id), _data_dir(request)
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except gate.ApprovalError as exc:
        raise HTTPException(422, str(exc)) from exc
    session.commit()
    return RedirectResponse(f"/approvals/{approval.id}", status_code=303)


# ---------- follow-ups ----------


@router.get("/follow-ups", response_class=HTMLResponse)
def follow_ups_page(request: Request, session: SessionDep) -> HTMLResponse:
    return _render(request, "follow_ups.html", {"rows": gate.open_follow_ups(session)})


@router.post("/applications/{app_id}/follow-ups")
async def add_follow_up(app_id: str, request: Request, session: SessionDep) -> Response:
    f = await request.form()
    due = _parse_local(
        (forms.text(f, "due") or "") + "T09:00" if forms.text(f, "due") else None,
        request.app.state.settings.display_timezone,
    )
    if due is None:
        return _app_error(request, session, app_id, ["Pick a valid due date."])
    try:
        gate.add_follow_up(
            session,
            app_id,
            due,
            forms.text(f, "action_type") or "follow_up",
            forms.text(f, "notes"),
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    return RedirectResponse(f"/applications/{app_id}#follow-ups", status_code=303)


@router.post("/follow-ups/{follow_up_id}/close")
async def close_follow_up(follow_up_id: str, request: Request, session: SessionDep) -> Response:
    f = await request.form()
    status = forms.text(f, "status")
    if status not in ("done", "skipped"):
        raise HTTPException(422, "Unknown status")
    try:
        fu = gate.close_follow_up(session, follow_up_id, cast(Any, status))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    back = forms.text(f, "back")
    target = (
        back if back in ("/follow-ups", "/") else f"/applications/{fu.application_id}#follow-ups"
    )
    return RedirectResponse(target, status_code=303)
