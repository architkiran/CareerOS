from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.modules.agents.service import start_monitor_mission
from careeros.modules.jobs.service import JobFilters, list_jobs
from careeros.modules.sources.monitoring import coverage
from careeros.modules.system.settings_store import get_setting, set_setting
from careeros.web.csrf import verify_csrf
from careeros.web.deps import get_session

router = APIRouter(dependencies=[Depends(verify_csrf)])
SessionDep = Annotated[Session, Depends(get_session)]


def watch_context(session: Session) -> dict[str, object]:
    heartbeat = get_setting(session, "worker.last_seen_at")
    recent = bool(
        heartbeat and utcnow() - datetime.fromisoformat(heartbeat) < timedelta(seconds=75)
    )
    seen = get_setting(session, "watch.seen_at") or (utcnow() - timedelta(days=1)).isoformat()
    rows, total = list_jobs(
        session,
        JobFilters(recommended=True, first_seen_after=datetime.fromisoformat(seen), sort="newest"),
    )
    return {
        "enabled": get_setting(session, "watch.enabled", False),
        "sources": coverage(session),
        "worker_recent": recent,
        "alerts": rows,
        "total": total,
    }


@router.get("/watch")
def page(request: Request, session: SessionDep) -> HTMLResponse:
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request,
        "watch.html",
        watch_context(session),
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/watch/toggle")
def toggle(session: SessionDep) -> RedirectResponse:
    enabled = not bool(get_setting(session, "watch.enabled", False))
    set_setting(session, "watch.enabled", enabled)
    if enabled and not get_setting(session, "watch.seen_at"):
        set_setting(session, "watch.seen_at", utcnow().isoformat())
    session.commit()
    return RedirectResponse("/watch", 303)


@router.post("/watch/read")
def read(session: SessionDep) -> RedirectResponse:
    set_setting(session, "watch.seen_at", utcnow().isoformat())
    session.commit()
    return RedirectResponse("/watch", 303)


@router.post("/watch/check")
def check(session: SessionDep) -> RedirectResponse:
    now = utcnow()
    due = [r.id for r in coverage(session, now) if r.next_due <= now and r.state != "Checking"][:5]
    if due:
        start_monitor_mission(session, due)
        session.commit()
    return RedirectResponse("/agents", 303)


@router.get("/partials/watch")
def partial(request: Request, session: SessionDep) -> HTMLResponse:
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request, "_watch_alerts.html", watch_context(session)
    )
    response.headers["Cache-Control"] = "no-store"
    return response
