"""The three-screen manual job-search workflow; optional tools remain independently routed."""

from typing import Annotated, Any
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import Job, RoleLane
from careeros.modules.events.service import record_event
from careeros.modules.jobs import inbox
from careeros.modules.jobs import service as jobs
from careeros.modules.jobs.sponsorship import LABELS
from careeros.modules.sources import monitoring
from careeros.modules.system.settings_store import set_setting
from careeros.modules.system.status import get_system_status
from careeros.web import forms
from careeros.web.csrf import verify_csrf
from careeros.web.deps import get_session

router = APIRouter(dependencies=[Depends(verify_csrf)])
SessionDep = Annotated[Session, Depends(get_session)]


def _return(value: str | None) -> str:
    if value and len(value) <= 2000:
        parsed = urlsplit(value)
        allowed = ("/new-jobs", "/saved-jobs", "/today")
        if not parsed.scheme and not parsed.netloc and parsed.path in allowed:
            return value
    return "/new-jobs"


def _context(
    request: Request, session: Session, *, saved: bool = False, navigation: bool = False
) -> dict[str, Any]:
    ready = get_system_status(
        request.app.state.settings, request.app.state.engine
    ).schema.up_to_date
    if not ready:
        return {"ready": False, "saved_view": saved}
    q = request.query_params
    cutoff = inbox.visit_cutoff(session, navigation=navigation)
    mode = q.get("mode", "new")
    if mode not in ("new", "unreviewed", "all", "fresh"):
        mode = "new"
    sponsor = q.get("sponsorship")
    if sponsor not in LABELS:
        sponsor = None
    seniority = q.get("seniority")
    if seniority not in ("entry", "junior", "mid", "senior", "lead", "executive"):
        seniority = None
    page = forms.bounded_int(q.get("page"), 1, 10000) or 1
    filters = jobs.JobFilters(
        q=(q.get("q") or "").strip()[:200] or None,
        lane_id=q.get("lane_id") or None,
        location=(q.get("location") or "").strip()[:100] or None,
        workplace=q.get("workplace")
        if q.get("workplace") in ("remote", "hybrid", "onsite")
        else None,
        seniority=seniority,
        sponsorship=sponsor,
        days=forms.bounded_int(q.get("days"), 1, 365),
        status="all" if saved else "active",
        eligibility="any" if saved else "not_fail",
        saved_only=saved,
        unreviewed=not saved and mode in ("new", "unreviewed"),
        first_seen_after=cutoff if not saved and mode == "new" else None,
        recommended=not saved and inbox.has_lanes(session),
        exclude_applied=not saved,
        published_minutes=1440 if not saved and mode == "fresh" else None,
        sort="published",
        page=page,
    )
    rows, total = jobs.list_jobs(session, filters)
    params = {
        k: v
        for k, v in dict(q).items()
        if k
        in ("q", "lane_id", "location", "workplace", "seniority", "sponsorship", "days", "mode")
        and v
    }
    base = "/saved-jobs" if saved else "/new-jobs"
    query = urlencode(params)
    return_to = base + ("?" + urlencode({**params, "page": page}) if params or page > 1 else "")
    ctx = {
        "ready": True,
        "saved_view": saved,
        "filters": filters,
        "mode": mode,
        "cards": inbox.cards(session, rows, cutoff),
        "total": total,
        "counts": inbox.counts(session, cutoff),
        "refresh": inbox.refresh_overview(session),
        "cutoff": cutoff,
        "sponsorship_labels": LABELS,
        "lanes": list(
            session.scalars(
                select(RoleLane).where(RoleLane.enabled.is_(True)).order_by(RoleLane.name)
            )
        ),
        "page": page,
        "pages": max(1, (total + jobs.PAGE_SIZE - 1) // jobs.PAGE_SIZE),
        "query": query,
        "base_url": base,
        "return_to": return_to,
        "partial_url": "/partials/inbox?"
        + urlencode({**params, "page": page, "screen": "saved" if saved else "new"}),
        "today": utcnow().astimezone(ZoneInfo(request.app.state.settings.display_timezone)).date(),
        "refresh_message": q.get("refresh"),
    }
    if navigation:
        session.commit()
    return ctx


def _render(request: Request, name: str, ctx: dict[str, Any]) -> HTMLResponse:
    result: HTMLResponse = request.app.state.templates.TemplateResponse(request, name, ctx)
    result.headers["Cache-Control"] = "no-store"
    return result


@router.get("/new-jobs", response_class=HTMLResponse)
def new_jobs(request: Request, session: SessionDep) -> HTMLResponse:
    return _render(request, "inbox.html", _context(request, session, navigation=True))


@router.get("/saved-jobs", response_class=HTMLResponse)
def saved_jobs(request: Request, session: SessionDep) -> HTMLResponse:
    return _render(request, "inbox.html", _context(request, session, saved=True))


@router.get("/partials/inbox", response_class=HTMLResponse)
def partial(request: Request, session: SessionDep) -> HTMLResponse:
    return _render(
        request,
        "_inbox_results.html",
        _context(request, session, saved=request.query_params.get("screen") == "saved"),
    )


@router.post("/inbox/refresh")
def refresh_jobs(session: SessionDep) -> RedirectResponse:
    _, state = monitoring.refresh(session)
    session.commit()
    return RedirectResponse(f"/new-jobs?refresh={state}", 303)


@router.post("/inbox/schedule")
async def schedule(request: Request, session: SessionDep) -> RedirectResponse:
    f = await request.form()
    value = forms.bounded_int(forms.text(f, "minutes"), 15, 1440)
    if value is None:
        raise HTTPException(422, "Choose a refresh interval from 15 to 1440 minutes.")
    monitoring.set_interval(session, value)
    set_setting(session, "watch.enabled", forms.checkbox(f, "enabled"))
    record_event(session, "discovery.schedule_updated", "User changed the discovery schedule.")
    session.commit()
    return RedirectResponse("/settings?discovery=saved#discovery", 303)


@router.post("/inbox/jobs/{job_id}/decision")
async def decision(job_id: str, request: Request, session: SessionDep) -> RedirectResponse:
    f = await request.form()
    action = forms.text(f, "action")
    if action not in ("save", "dismiss", "review"):
        raise HTTPException(422, "Choose Save, Dismiss, or Mark reviewed.")
    try:
        job = jobs.triage(
            session,
            job_id,
            {"save": "save", "dismiss": "reject", "review": "reviewed"}[action],  # type: ignore[arg-type]
            "Dismissed by the user" if action == "dismiss" else None,
        )
        if action == "dismiss" and job.saved_stage:
            job.saved_stage = "rejected"
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    return RedirectResponse(_return(forms.text(f, "return_to")), 303)


@router.post("/inbox/jobs/{job_id}/saved-status")
async def saved_status(job_id: str, request: Request, session: SessionDep) -> RedirectResponse:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    f = await request.form()
    stage, next_action = forms.text(f, "stage"), forms.text(f, "next_action")
    if stage not in ("saved", "reviewing", "rejected") or (next_action and len(next_action) > 500):
        raise HTTPException(
            422, "Choose a shortlist status and keep the next action within 500 characters."
        )
    job.saved_stage, job.next_action = stage, next_action
    job.triage_status = "rejected" if stage == "rejected" else "saved"
    job.triaged_at = utcnow()
    record_event(
        session,
        "job.shortlist_updated",
        "User updated a saved job.",
        entity_type="job",
        entity_id=job.id,
    )
    session.commit()
    return RedirectResponse("/saved-jobs", 303)


@router.post("/inbox/review-page")
async def review_page(request: Request, session: SessionDep) -> RedirectResponse:
    f = await request.form()
    ids = [v for v in f.getlist("job_id") if isinstance(v, str)]
    if not ids or len(ids) > jobs.PAGE_SIZE:
        raise HTTPException(422, "Choose up to one displayed page of jobs.")
    changed = list(
        session.scalars(
            update(Job)
            .where(Job.id.in_(ids), Job.triage_status == "new", Job.saved_stage.is_(None))
            .values(triage_status="reviewed", triaged_at=utcnow())
            .returning(Job.id)
        )
    )
    record_event(
        session,
        "job.page_reviewed",
        "User marked the displayed page reviewed.",
        metadata={"count": len(changed)},
    )
    session.commit()
    return RedirectResponse("/new-jobs", 303)


@router.post("/inbox/jobs/{job_id}/opened")
def opened(job_id: str, session: SessionDep) -> Response:
    if session.get(Job, job_id) is None:
        raise HTTPException(404, "Job not found")
    record_event(
        session,
        "job.original_opened",
        "User opened the original posting link.",
        entity_type="job",
        entity_id=job_id,
    )
    session.commit()
    return Response(status_code=204)


@router.post("/inbox/jobs/{job_id}/eligibility-review")
async def eligibility_review(
    job_id: str, request: Request, session: SessionDep
) -> RedirectResponse:
    if session.get(Job, job_id) is None:
        raise HTTPException(404, "Job not found")
    f = await request.form()
    value = forms.text(f, "decision")
    if value not in ("fits", "not_fit", "unsure"):
        raise HTTPException(422, "Choose a review result.")
    record_event(
        session,
        "job.eligibility_review",
        "User recorded their eligibility review.",
        entity_type="job",
        entity_id=job_id,
        metadata={"decision": value},
    )
    session.commit()
    return RedirectResponse("/saved-jobs", 303)


@router.post("/inbox/jobs/{job_id}/optional-tools")
def optional_tools(job_id: str, session: SessionDep) -> RedirectResponse:
    from careeros.modules.applications.service import start_application

    try:
        job = jobs.triage(session, job_id, "save")
        app = start_application(session, job.id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    return RedirectResponse(f"/applications/{app.id}?advanced=1", 303)
