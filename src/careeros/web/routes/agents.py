"""Mission Control reads persisted state; all mutations require the existing CSRF gate."""

from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import AgentAttempt, AgentDependency, AgentRun, Mission, Source, Task
from careeros.modules.agents import service
from careeros.modules.agents.registry import AGENTS, BY_KEY, ON_DEMAND_AGENTS, PLANNED
from careeros.modules.applications import service as application_service
from careeros.modules.approvals import service as approval_service
from careeros.modules.backup.service import latest_backup
from careeros.modules.events.service import latest_events
from careeros.modules.jobs.service import (
    JobFilters,
    list_jobs,
    public_board_links,
    recommended_jobs,
)
from careeros.modules.models.gateway import usage_summary
from careeros.modules.profile.service import profile_summary
from careeros.modules.system.overview import build_overview
from careeros.modules.system.settings_store import get_setting
from careeros.modules.system.status import get_system_status
from careeros.web.csrf import verify_csrf
from careeros.web.deps import get_session

router = APIRouter(dependencies=[Depends(verify_csrf)])
SessionDep = Annotated[Session, Depends(get_session)]


def _ready(request: Request) -> None:
    status = get_system_status(request.app.state.settings, request.app.state.engine)
    if not status.schema.up_to_date:
        raise HTTPException(409, "Run careeros migrate before starting or changing missions.")


def _render(request: Request, name: str, context: dict[str, Any]) -> HTMLResponse:
    response: HTMLResponse = request.app.state.templates.TemplateResponse(request, name, context)
    response.headers["Cache-Control"] = "no-store"
    return response


def _context(request: Request, session: Session) -> dict[str, Any]:
    state = request.app.state
    status = get_system_status(state.settings, state.engine)
    ctx: dict[str, Any] = {"status": status, "mc": None, "planned": PLANNED}
    if not status.schema.up_to_date:
        return ctx
    missions = list(session.scalars(select(Mission).order_by(Mission.created_at.desc()).limit(20)))
    current = service.active_mission(session) or next(
        (m for m in missions if m.workflow == "career-review"), None
    )
    runs = service.runs_for(session, current.id) if current else []
    by_key = {run.agent_key: run for run in runs}
    events = latest_events(session)
    opportunities = recommended_jobs(session)
    arrivals, arrivals_total = list_jobs(
        session, JobFilters(recommended=True, sort="newest", days=7, min_score=50)
    )
    published, published_total = list_jobs(
        session, JobFilters(recommended=True, sort="published", published_minutes=1440)
    )
    heartbeat = get_setting(session, "worker.last_seen_at")
    seen = datetime.fromisoformat(heartbeat) if isinstance(heartbeat, str) else None
    scheduled = get_setting(session, service.LAST_SCHEDULED_KEY)
    next_run = (
        datetime.fromisoformat(scheduled) + timedelta(hours=state.settings.schedule_interval_hours)
        if isinstance(scheduled, str)
        else None
    )
    from careeros.modules.referrals.service import overview as referral_overview

    ctx["mc"] = {
        "referrals": referral_overview(session),
        "background_tasks": list(
            session.scalars(
                select(Task)
                .where(
                    Task.task_type.in_(("match.all", "ingest.all", "ingest.source")),
                    Task.status.in_(("queued", "running", "dead")),
                )
                .order_by(Task.created_at.desc())
                .limit(10)
            )
        ),
        "task_labels": {
            "match.all": "Opportunity matching",
            "ingest.all": "Job discovery",
            "ingest.source": "Employer feed check",
        },
        "recent_runs": list(
            session.execute(
                select(AgentRun, Mission)
                .join(Mission)
                .order_by(Mission.created_at.desc(), AgentRun.position)
                .limit(40)
            ).all()
        ),
        "active_runs": list(
            session.execute(
                select(AgentRun, Mission)
                .join(Mission)
                .where(
                    Mission.status.in_(("queued", "running")),
                    AgentRun.status.in_(("queued", "running", "retrying")),
                )
                .order_by(AgentRun.started_at, AgentRun.position)
                .limit(20)
            ).all()
        ),
        "specs": BY_KEY,
        "mission": current,
        "missions": missions,
        "runs": runs,
        "completed": sum(run.status == "succeeded" for run in runs),
        "cards": [(spec, by_key.get(spec.key)) for spec in AGENTS],
        "extra_cards": [
            (
                spec,
                session.scalars(
                    select(AgentRun)
                    .join(Mission)
                    .where(AgentRun.agent_key == spec.key)
                    .order_by(Mission.created_at.desc())
                    .limit(1)
                ).first(),
            )
            for spec in ON_DEMAND_AGENTS
        ],
        "ov": build_overview(session, state.settings),
        "events": events,
        "cursor": events[0].id if events else 0,
        "published_arrivals": published[:4],
        "published_total": published_total,
        "arrivals": arrivals[:4],
        "arrivals_total": arrivals_total,
        "opportunities": opportunities[:3],
        "board_links": public_board_links(
            session, [row.job.id for row in [*opportunities, *published, *arrivals]]
        ),
        "profile": profile_summary(session),
        "followups": approval_service.open_follow_ups(session, due_within_days=3)[:3],
        "application_rows": application_service.list_applications(session)[:3],
        "usage": usage_summary(session),
        "worker_seen": seen,
        "worker_recent": seen is not None and utcnow() - seen < timedelta(seconds=75),
        "schedule_enabled": state.settings.mission_scheduler_enabled,
        "next_run": next_run,
        "backup": latest_backup(state.settings.backup_dir),
        "monitor_enabled": get_setting(session, "watch.enabled", False),
        "last_source_refresh": session.scalar(select(func.max(Source.last_success_at))),
    }
    return ctx


@router.get("/mission-control", response_class=HTMLResponse)
def mission_control(request: Request, session: SessionDep) -> HTMLResponse:
    return _render(request, "mission_control.html", _context(request, session))


@router.get("/partials/mission-control", response_class=HTMLResponse)
def mission_partial(request: Request, session: SessionDep) -> HTMLResponse:
    return _render(request, "_mission_control.html", _context(request, session))


@router.post("/missions")
def start(request: Request, session: SessionDep) -> RedirectResponse:
    _ready(request)
    mission, _ = service.start_mission(session)
    session.commit()
    return RedirectResponse(f"/missions/{mission.id}", status_code=303)


@router.get("/missions/{mission_id}", response_class=HTMLResponse)
def detail(mission_id: str, request: Request, session: SessionDep) -> HTMLResponse:
    _ready(request)
    mission = session.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(404, "Mission not found")
    runs = service.runs_for(session, mission_id)
    attempts = list(
        session.scalars(
            select(AgentAttempt)
            .where(AgentAttempt.run_id.in_([r.id for r in runs]))
            .order_by(AgentAttempt.started_at, AgentAttempt.number)
        )
    )
    deps = list(
        session.scalars(
            select(AgentDependency).where(AgentDependency.run_id.in_([r.id for r in runs]))
        )
    )
    return _render(
        request,
        "mission_detail.html",
        {
            "mission": mission,
            "runs": runs,
            "attempts": attempts,
            "specs": BY_KEY,
            "dependencies": deps,
            "by_id": {r.id: r for r in runs},
            "tasks": {r.task_id: session.get(Task, r.task_id) for r in runs if r.task_id},
        },
    )


@router.post("/missions/{mission_id}/{action}")
def control(
    mission_id: str, action: str, request: Request, session: SessionDep
) -> RedirectResponse:
    _ready(request)
    try:
        service.control_mission(session, mission_id, action)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except service.MissionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return RedirectResponse(f"/missions/{mission_id}", status_code=303)


@router.post("/agent-runs/{run_id}/retry")
def retry(run_id: str, request: Request, session: SessionDep) -> RedirectResponse:
    _ready(request)
    try:
        service.retry_run(session, run_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except service.MissionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    run = session.get(AgentRun, run_id)
    assert run
    return RedirectResponse(f"/missions/{run.mission_id}", status_code=303)


@router.get("/agents", response_class=HTMLResponse)
def agent_index(request: Request, session: SessionDep) -> HTMLResponse:
    return _render(request, "agents.html", _context(request, session))


@router.get("/partials/agents", response_class=HTMLResponse)
def agent_partial(request: Request, session: SessionDep) -> HTMLResponse:
    return _render(request, "_agent_activity.html", _context(request, session))


@router.get("/agents/{key}", response_class=HTMLResponse)
def agent_workspace(key: str, request: Request, session: SessionDep) -> HTMLResponse:
    _ready(request)
    spec = BY_KEY.get(key)
    if spec is None:
        raise HTTPException(404, "Agent not found")
    runs = list(
        session.scalars(
            select(AgentRun)
            .join(Mission)
            .where(AgentRun.agent_key == key)
            .order_by(Mission.created_at.desc())
            .limit(30)
        )
    )
    return _render(request, "agent_workspace.html", {"spec": spec, "runs": runs})
