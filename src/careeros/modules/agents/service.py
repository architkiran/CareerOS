"""Durable state transitions. Queue completion and downstream handoffs share a transaction."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import (
    AgentAttempt,
    AgentDependency,
    AgentRun,
    Application,
    Job,
    Mission,
    Task,
)
from careeros.modules.agents.contracts import AgentOutput
from careeros.modules.agents.registry import AGENTS, BY_KEY, TASK_TYPE, VERSION, WORKFLOW
from careeros.modules.events.service import record_event
from careeros.modules.scheduler import queue
from careeros.modules.system.settings_store import get_setting, set_setting

ACTIVE = ("queued", "running", "paused")
LAST_SCHEDULED_KEY = "agents.last_scheduled_at"


class MissionConflict(ValueError):
    pass


def runs_for(session: Session, mission_id: str) -> list[AgentRun]:
    return list(
        session.scalars(
            select(AgentRun).where(AgentRun.mission_id == mission_id).order_by(AgentRun.position)
        )
    )


def active_mission(session: Session) -> Mission | None:
    return session.scalars(
        select(Mission).where(Mission.workflow == WORKFLOW, Mission.status.in_(ACTIVE))
    ).first()


def mission_label(mission: Mission) -> str:
    if mission.workflow.startswith("tailoring:"):
        return "Resume rewrite"
    if mission.workflow.startswith("interview:"):
        return "Interview preparation"
    if mission.workflow.startswith("application:"):
        return "Application draft preparation"
    if mission.workflow.startswith("networking:"):
        return "Networking research"
    if mission.workflow.startswith("evidence:"):
        return "Application evidence mapping"
    if mission.workflow.startswith("freshness:"):
        return "Freshness monitoring"
    if mission.workflow.startswith("sources:"):
        return "Source coverage review"
    return "Career review"


def _event(session: Session, mission: Mission, kind: str, message: str) -> None:
    record_event(session, f"mission.{kind}", message, entity_type="mission", entity_id=mission.id)


def _queue_run(session: Session, run: AgentRun) -> None:
    payload: dict[str, Any] = {"agent_run_id": run.id}
    mission = session.get(Mission, run.mission_id)
    if run.agent_key == "discovery" and mission and mission.trigger == "schedule":
        from careeros.modules.sources.registry import due_source_ids

        payload["source_ids"] = due_source_ids(session)
    task, _ = queue.enqueue(
        session,
        TASK_TYPE,
        payload,
        idempotency_key=f"agent:{run.id}",
    )
    run.task_id, run.status = task.id, "queued"


def _write_lock(session: Session) -> None:
    # Start a real SQLite write transaction before SAVEPOINT. Without this, sqlite3's
    # legacy transaction mode can commit a released savepoint independently of rollback.
    session.execute(
        update(Mission)
        .where(Mission.workflow == WORKFLOW, Mission.status.in_(ACTIVE))
        .values(workflow=WORKFLOW)
    )


def start_mission(session: Session, trigger: str = "manual") -> tuple[Mission, bool]:
    if trigger not in ("manual", "schedule"):
        raise ValueError("Unsupported mission trigger")
    _write_lock(session)
    existing = active_mission(session)
    if existing is not None:
        return existing, False
    mission = Mission(workflow=WORKFLOW, version=VERSION, trigger=trigger)
    try:
        with session.begin_nested():
            session.add(mission)
            session.flush()
    except IntegrityError:
        existing = active_mission(session)
        if existing is None:
            raise
        return existing, False
    runs: dict[str, AgentRun] = {}
    for position, spec in enumerate(AGENTS):
        run = AgentRun(mission_id=mission.id, agent_key=spec.key, position=position)
        session.add(run)
        session.flush()
        runs[spec.key] = run
    for spec in AGENTS:
        for dep in spec.dependencies:
            session.add(AgentDependency(run_id=runs[spec.key].id, depends_on_id=runs[dep].id))
        if not spec.dependencies:
            _queue_run(session, runs[spec.key])
    _event(session, mission, "queued", "Career review queued: discovery through quality checks.")
    return mission, True


def _advance(session: Session, mission: Mission) -> None:
    if mission.status not in ("queued", "running"):
        return
    session.flush()
    runs = runs_for(session, mission.id)
    by_id = {run.id: run for run in runs}
    for run in runs:
        if run.status != "blocked":
            continue
        dependencies = list(
            session.scalars(
                select(AgentDependency.depends_on_id).where(AgentDependency.run_id == run.id)
            )
        )
        if all(by_id[dep].status == "succeeded" for dep in dependencies):
            _queue_run(session, run)
            _event(session, mission, "handoff", f"Ready for {BY_KEY[run.agent_key].name.lower()}.")
    if all(run.status == "succeeded" for run in runs):
        has_warnings = any(run.result_json.get("warnings") for run in runs)
        mission.status = "degraded" if has_warnings else "succeeded"
        mission.finished_at = utcnow()
        _event(
            session,
            mission,
            "completed",
            (
                f"{mission_label(mission)} completed with items needing attention."
                if has_warnings
                else f"{mission_label(mission)} completed. Your results are ready."
            ),
        )


def run_for_task(session: Session, task: Task) -> AgentRun | None:
    if task.task_type != TASK_TYPE:
        return None
    return session.scalars(select(AgentRun).where(AgentRun.task_id == task.id)).one_or_none()


def begin_task(session: Session, task: Task) -> None:
    run = run_for_task(session, task)
    if run is None:
        return
    mission = session.get(Mission, run.mission_id)
    assert mission is not None
    # A reclaimed lease closes the interrupted attempt instead of losing its history.
    old = list(
        session.scalars(
            select(AgentAttempt).where(
                AgentAttempt.run_id == run.id, AgentAttempt.status == "running"
            )
        )
    )
    for attempt in old:
        attempt.status, attempt.finished_at = "interrupted", utcnow()
        attempt.error = "Worker lease expired; this step was reclaimed."
    number = (
        int(
            session.scalar(
                select(func.max(AgentAttempt.number)).where(AgentAttempt.run_id == run.id)
            )
            or 0
        )
        + 1
    )
    session.add(AgentAttempt(run_id=run.id, number=number, worker_id=task.locked_by or "unknown"))
    run.status, run.finished_at = "running", None
    run.started_at = run.started_at or utcnow()
    mission.started_at = mission.started_at or utcnow()
    if mission.status == "queued":
        mission.status = "running"
    _event(session, mission, "step_started", f"{BY_KEY[run.agent_key].name} started.")


def finish_task(
    session: Session, task: Task, *, result: dict[str, Any] | None = None, error: str | None = None
) -> None:
    run = run_for_task(session, task)
    if run is None:
        return
    mission = session.get(Mission, run.mission_id)
    assert mission is not None
    attempt = session.scalars(
        select(AgentAttempt).where(AgentAttempt.run_id == run.id, AgentAttempt.status == "running")
    ).one()
    attempt.finished_at = utcnow()
    attempt.status = "failed" if error else "succeeded"
    attempt.error = error
    if mission.status == "cancelled":
        task.status = run.status = "cancelled"
        task.finished_at = run.finished_at = utcnow()
        return
    if error:
        run.last_error = error
        run.status = "failed" if task.status == queue.DEAD else "retrying"
        if task.status == queue.DEAD:
            run.finished_at = mission.finished_at = utcnow()
            mission.status = "failed"
            _event(session, mission, "failed", f"{BY_KEY[run.agent_key].name} needs recovery.")
        elif mission.status == "paused":
            task.status = "paused"
        return
    output = AgentOutput.model_validate(result)
    run.result_json = output.model_dump()
    run.summary, run.last_error, run.status = output.summary, None, "succeeded"
    run.finished_at = utcnow()
    _event(session, mission, "step_completed", output.summary)
    _advance(session, mission)


def retry_run(session: Session, run_id: str) -> None:
    _write_lock(session)
    run = session.get(AgentRun, run_id)
    if run is None:
        raise LookupError("Agent run not found")
    mission = session.get(Mission, run.mission_id)
    assert mission is not None
    if run.status != "failed" or not run.task_id or mission.status != "failed":
        raise MissionConflict("Only a failed step in a failed mission can be retried.")
    # Acquire the active-workflow slot before touching the old task.
    other = session.scalars(
        select(Mission).where(Mission.workflow == mission.workflow, Mission.status.in_(ACTIVE))
    ).first()
    if other is not None:
        label = mission_label(mission).lower()
        raise MissionConflict(f"Finish or cancel the active {label} before retrying this one.")
    try:
        with session.begin_nested():
            mission.status, mission.finished_at = "running", None
            session.flush()
    except IntegrityError as exc:
        raise MissionConflict("Another career review is already active.") from exc
    queue.retry_dead(session, run.task_id)
    run.status, run.finished_at = "queued", None
    _event(
        session, mission, "resumed", f"Retry requested for {BY_KEY[run.agent_key].name.lower()}."
    )


def control_mission(session: Session, mission_id: str, action: str) -> None:
    # SQLite serializes this write with claim/finish, preventing a pause/claim race.
    session.execute(update(Mission).where(Mission.id == mission_id).values(id=mission_id))
    mission = session.get(Mission, mission_id, populate_existing=True)
    if mission is None:
        raise LookupError("Mission not found")
    expected = {"pause": ("queued", "running"), "resume": ("paused",), "cancel": ACTIVE}
    if action not in expected or mission.status not in expected[action]:
        raise MissionConflict("This action is not available for the current mission state.")
    mission.status = {"pause": "paused", "resume": "running", "cancel": "cancelled"}[action]
    for run in runs_for(session, mission.id):
        task = session.get(Task, run.task_id, populate_existing=True) if run.task_id else None
        if action == "pause" and task and task.status == queue.QUEUED:
            task.status = "paused"
        elif action == "resume" and task and task.status == "paused":
            task.status = queue.QUEUED
        elif (
            action == "cancel"
            and run.status not in ("succeeded", "failed")
            and not (task and task.status == queue.RUNNING)
        ):
            run.status, run.finished_at = "cancelled", utcnow()
            if task:
                task.status, task.finished_at = "cancelled", utcnow()
    if action == "cancel":
        mission.finished_at = utcnow()
    if action == "resume":
        _advance(session, mission)
    _event(
        session,
        mission,
        action,
        {
            "pause": f"{mission_label(mission)} paused. "
            "The current step may finish; no new steps will start.",
            "resume": f"{mission_label(mission)} resumed.",
            "cancel": f"{mission_label(mission)} cancelled. An in-flight step may finish; "
            "no new steps will start.",
        }[action],
    )


def maybe_schedule(session: Session, hours: float, now: datetime | None = None) -> bool:
    now = now or utcnow()
    value = get_setting(session, LAST_SCHEDULED_KEY)
    last = datetime.fromisoformat(value) if isinstance(value, str) else None
    if last is not None and now - last < timedelta(hours=hours):
        return False
    _, created = start_mission(session, "schedule")
    # A paused/active mission is not a completed scheduling tick: try again later.
    if created:
        set_setting(session, LAST_SCHEDULED_KEY, now.isoformat())
    session.commit()
    return created


def start_interview_mission(session: Session, job_id: str) -> tuple[Mission, bool]:
    """One on-demand interview preparation at a time per job; no application side effects."""
    if session.get(Job, job_id) is None:
        raise LookupError("Job not found")
    return _start_on_demand(session, "interview", job_id, {"job_id": job_id})


def start_application_mission(session: Session, application_id: str) -> tuple[Mission, bool]:
    app = session.get(Application, application_id)
    if app is None:
        raise LookupError("Application not found")
    if app.status not in ("preparing", "ready"):
        raise MissionConflict("Draft preparation is available for applications being prepared.")
    return _start_on_demand(
        session, "application", application_id, {"application_id": application_id}
    )


def _start_on_demand(
    session: Session, key: str, target_id: str, inputs: dict[str, Any]
) -> tuple[Mission, bool]:
    _write_lock(session)
    workflow = f"{key}:{target_id}"
    existing = session.scalars(
        select(Mission).where(Mission.workflow == workflow, Mission.status.in_(ACTIVE))
    ).first()
    if existing:
        return existing, False
    mission = Mission(workflow=workflow, version=VERSION, trigger="manual")
    try:
        with session.begin_nested():
            session.add(mission)
            session.flush()
    except IntegrityError:
        return session.scalars(
            select(Mission).where(Mission.workflow == workflow, Mission.status.in_(ACTIVE))
        ).one(), False
    run = AgentRun(mission_id=mission.id, agent_key=key, position=0)
    session.add(run)
    session.flush()
    task, _ = queue.enqueue(
        session,
        TASK_TYPE,
        {"agent_run_id": run.id, **inputs},
        idempotency_key=f"agent:{run.id}",
    )
    run.task_id, run.status = task.id, "queued"
    _event(
        session,
        mission,
        "queued",
        f"{mission_label(mission)} queued. No application or message will be sent.",
    )
    return mission, True


def start_source_mission(session: Session) -> tuple[Mission, bool]:
    return _start_on_demand(session, "sources", "catalog", {})


def start_support_mission(session: Session, application_id: str, kind: str) -> tuple[Mission, bool]:
    if kind not in ("evidence", "networking") or session.get(Application, application_id) is None:
        raise LookupError("Unknown application research task")
    return _start_on_demand(session, kind, application_id, {"application_id": application_id})


def start_monitor_mission(session: Session, source_ids: list[str]) -> tuple[Mission, bool]:
    return _start_on_demand(session, "freshness", "watch", {"source_ids": source_ids})


def start_rewrite_mission(session: Session, application_id: str) -> tuple[Mission, bool]:
    app = session.get(Application, application_id)
    if app is None or app.status not in ("preparing", "ready"):
        raise ValueError("Only draft applications can be tailored.")
    return _start_on_demand(
        session, "tailoring", application_id, {"application_id": application_id}
    )
