from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from careeros.db.models import ResearchItem
from careeros.modules.research import service as research
from careeros.modules.scheduler.worker import enqueue_rescore
from careeros.web import forms
from careeros.web.csrf import verify_csrf
from careeros.web.deps import error_messages, get_session

router = APIRouter(dependencies=[Depends(verify_csrf)])
SessionDep = Annotated[Session, Depends(get_session)]


def _job_redirect(session: Session, item_id: str, flash: str = "saved=1") -> RedirectResponse:
    item = session.get(ResearchItem, item_id)
    target = f"/jobs/{item.job_id}?{flash}#research" if item and item.job_id else "/research"
    return RedirectResponse(target, status_code=303)


@router.get("/research", response_class=HTMLResponse)
def queue_page(request: Request, session: SessionDep, status: str | None = None) -> HTMLResponse:
    if status not in (None, "", "open", "in_progress", "done"):
        status = None
    rows = research.research_queue(session, status or None)
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request,
        "research.html",
        {"rows": rows, "status": status, "policy_labels": research.POLICY_LABELS},
    )
    return response


@router.post("/jobs/{job_id}/research")
def start(job_id: str, session: SessionDep) -> Response:
    try:
        item = research.open_research(session, job_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    return _job_redirect(session, item.id)


@router.post("/research/{item_id}/evidence")
async def add(item_id: str, request: Request, session: SessionDep) -> Response:
    f = await request.form()
    try:
        data = research.EvidenceIn(
            claim_type=cast(Any, forms.text(f, "claim_type")),
            claim_text=forms.text(f, "claim_text") or "",
            source_kind=cast(Any, forms.text(f, "source_kind")),
            source_url=forms.text(f, "source_url") or "",
            source_title=forms.text(f, "source_title"),
            source_date=cast(Any, forms.text(f, "source_date")),
            short_excerpt=forms.text(f, "short_excerpt"),
            confidence=cast(Any, forms.text(f, "confidence") or "medium"),
            checked=forms.checkbox(f, "checked"),
        )
        research.add_evidence(session, item_id, data)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValidationError as exc:
        session.rollback()
        return _error(request, session, item_id, error_messages(exc))
    enqueue_rescore(session, "employer evidence changed")
    session.commit()
    return _job_redirect(session, item_id)


def _error(request: Request, session: Session, item_id: str, errors: list[str]) -> HTMLResponse:
    from careeros.web.routes.jobs import job_detail_response

    item = session.get(ResearchItem, item_id)
    if item is None or item.job_id is None:
        raise HTTPException(422, "; ".join(errors))
    return job_detail_response(request, session, item.job_id, {"errors": errors}, 422)


@router.post("/evidence/{evidence_id}/review")
async def review(evidence_id: str, request: Request, session: SessionDep) -> Response:
    f = await request.form()
    decision = forms.text(f, "decision") or ""
    if decision not in ("accepted", "rejected", "pending"):
        raise HTTPException(422, "Unknown decision")
    try:
        ev = research.review_evidence(session, evidence_id, cast(Any, decision))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    enqueue_rescore(session, "employer evidence changed")
    session.commit()
    if ev.research_item_id:
        return _job_redirect(session, ev.research_item_id)
    return RedirectResponse("/research", status_code=303)


@router.post("/research/{item_id}/complete")
async def complete(item_id: str, request: Request, session: SessionDep) -> Response:
    f = await request.form()
    try:
        research.complete_research(session, item_id, forms.text(f, "summary"))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    return _job_redirect(session, item_id)


@router.post("/research/{item_id}/reopen")
def reopen(item_id: str, session: SessionDep) -> Response:
    try:
        research.reopen_research(session, item_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    return _job_redirect(session, item_id)
