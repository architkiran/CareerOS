from typing import Annotated, Any, cast
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from careeros.modules.jobs import service as jobs
from careeros.modules.scheduler import queue
from careeros.modules.scheduler.worker import enqueue_discovery, enqueue_source
from careeros.modules.sources import registry
from careeros.modules.system.overview import build_overview
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
    return response


@router.get("/jobs", response_class=HTMLResponse)
def inbox(
    request: Request,
    session: SessionDep,
    q: str | None = None,
    triage: str | None = None,
    status: str = "active",
    source_id: str | None = None,
    workplace: str | None = None,
    days: int | None = Query(default=None, ge=1, le=365),
    dupes: bool = False,
    page: int = Query(default=1, ge=1, le=10_000),
) -> HTMLResponse:
    if triage and triage not in jobs.TRIAGE_STATUSES:
        triage = None
    if status not in ("active", "closed", "all"):
        status = "active"
    if workplace not in (None, "", "remote", "hybrid", "onsite"):
        workplace = None
    filters = jobs.JobFilters(
        q=(q or "").strip()[:200] or None,
        triage=triage,
        status=cast(Any, status),
        source_id=source_id or None,
        workplace=workplace or None,
        days=days,
        possible_duplicates=dupes,
        page=page,
    )
    rows, total = jobs.list_jobs(session, filters)
    params = {
        k: v
        for k, v in {
            "q": filters.q,
            "triage": triage,
            "status": status,
            "source_id": source_id,
            "workplace": workplace,
            "days": days,
            "dupes": "true" if dupes else None,
        }.items()
        if v
    }
    pages = max((total + jobs.PAGE_SIZE - 1) // jobs.PAGE_SIZE, 1)
    return _render(
        request,
        "jobs.html",
        {
            "rows": rows,
            "total": total,
            "filters": filters,
            "sources": registry.list_sources(session),
            "triage_statuses": jobs.TRIAGE_STATUSES,
            "page": page,
            "pages": pages,
            "query": urlencode(params),
            "any_jobs": total > 0 or bool(params.keys() - {"status"}),
        },
    )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(job_id: str, request: Request, session: SessionDep) -> HTMLResponse:
    detail = jobs.get_job_detail(session, job_id)
    if detail is None:
        raise HTTPException(404, "Job not found")
    return _render(request, "job_detail.html", {"d": detail})


@router.post("/jobs/{job_id}/triage")
async def triage_job(job_id: str, request: Request, session: SessionDep) -> Response:
    f = await request.form()
    action = forms.text(f, "action") or ""
    try:
        jobs.triage(session, job_id, cast(jobs.TriageAction, action), forms.text(f, "reason"))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except jobs.TriageError as exc:
        session.rollback()
        detail = jobs.get_job_detail(session, job_id)
        return _render(request, "job_detail.html", {"d": detail, "errors": [str(exc)]}, 422)
    session.commit()
    return RedirectResponse(f"/jobs/{job_id}?saved=1", status_code=303)


@router.post("/pipeline/run")
def run_pipeline(session: SessionDep) -> Response:
    _, created = enqueue_discovery(session, "manual")
    session.commit()
    return RedirectResponse(f"/?queued={'1' if created else 'already'}", status_code=303)


@router.post("/sources/{source_id}/run")
def run_source_now(source_id: str, session: SessionDep) -> Response:
    source = next((s for s in registry.list_sources(session) if s.id == source_id), None)
    if source is None:
        raise HTTPException(404, "Source not found")
    _, created = enqueue_source(session, source.id, source.display_name)
    session.commit()
    return RedirectResponse(f"/sources?queued={'1' if created else 'already'}", status_code=303)


@router.post("/tasks/{task_id}/retry")
def retry_task(task_id: str, session: SessionDep) -> Response:
    try:
        queue.retry_dead(session, task_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    return RedirectResponse("/?queued=1", status_code=303)


@router.get("/partials/overview", response_class=HTMLResponse)
def overview_partial(request: Request, session: SessionDep) -> HTMLResponse:
    ov = build_overview(session, request.app.state.settings)
    return _render(request, "_overview_stats.html", {"ov": ov})
