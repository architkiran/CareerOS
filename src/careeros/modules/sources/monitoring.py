"""Honest local polling: provider cadence is not a promise of publication latency."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import AgentRun, Source, Task
from careeros.modules.sources.registry import last_run, list_sources, source_policy
from careeros.modules.system.settings_store import get_setting, set_setting


@dataclass
class MonitorSource:
    id: str
    name: str
    minutes: int
    checked: datetime | None
    next_due: datetime
    state: str
    publication: str


DEFAULT_INTERVAL_MINUTES = 30
PROVIDER_MINUTES = {"remotive": 360, "jobicy": 60, "smartrecruiters": 60, "wwr": 60}


def interval_minutes(session: Session) -> int:
    value = get_setting(session, "watch.interval_minutes", DEFAULT_INTERVAL_MINUTES)
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and 15 <= value <= 1440
        else DEFAULT_INTERVAL_MINUTES
    )


def set_interval(session: Session, minutes: int) -> None:
    if isinstance(minutes, bool) or not 15 <= minutes <= 1440:
        raise ValueError("Refresh interval must be between 15 and 1440 minutes.")
    set_setting(session, "watch.interval_minutes", minutes)


def discovery_busy(session: Session) -> bool:
    return bool(
        session.scalar(
            select(Task.id)
            .where(
                Task.status.in_(("queued", "running")),
                Task.task_type.in_(("ingest.all", "ingest.source", "discovery")),
            )
            .limit(1)
        )
        or session.scalar(
            select(AgentRun.id)
            .where(
                AgentRun.agent_key.in_(("discovery", "freshness")),
                AgentRun.status.in_(("queued", "running", "retrying")),
            )
            .limit(1)
        )
    )


def coverage(session: Session, now: datetime | None = None) -> list[MonitorSource]:
    now = now or utcnow()
    rows = []
    for source in list_sources(session):
        if not source.enabled or source.source_type == "manual":
            continue
        run = last_run(session, source.id)
        minutes = max(
            interval_minutes(session),
            source_policy(source).refresh_interval_minutes or 15,
            PROVIDER_MINUTES.get(source.source_type, 15),
        )
        checked = run.started_at if run else None
        due = checked + timedelta(minutes=minutes) if checked else now
        state = (
            "Needs attention"
            if source.last_error
            else "Checking"
            if run and run.finished_at is None and now - run.started_at < timedelta(minutes=15)
            else "Interrupted"
            if run and run.finished_at is None
            else "Some items rejected"
            if run and run.status == "partial"
            else "Due now"
            if due <= now
            else "Scheduled"
        )
        publication = {
            "remotive": "Provider delays publication by 24h",
            "jobicy": "Public-board timestamp; hourly checks",
            "ashby": "Published/re-published time from source",
            "greenhouse": "Original publication only when source supplies it",
            "lever": "Source creation timestamp when supplied",
            "smartrecruiters": "Source release timestamp",
            "wwr": "RSS publication timestamp",
        }.get(source.source_type, "Source publication time may be unknown")
        rows.append(
            MonitorSource(source.id, source.display_name, minutes, checked, due, state, publication)
        )
    return rows


def tick(session: Session) -> None:
    if not get_setting(session, "watch.enabled", False):
        return
    now = utcnow()
    last = get_setting(session, "watch.last_tick")
    if last and now - datetime.fromisoformat(last) < timedelta(seconds=60):
        return
    set_setting(session, "watch.last_tick", now.isoformat())
    from careeros.modules.agents import service as agents

    if agents.active_mission(session) or discovery_busy(session):
        return
    due = [r.id for r in coverage(session, now) if r.next_due <= now and r.state != "Checking"][:5]
    if due:
        agents.start_monitor_mission(session, due)


def refresh(session: Session) -> tuple[str | None, str]:
    """Manual refresh honors provider cooldowns and reuses in-flight discovery."""
    from careeros.modules.agents import service as agents

    if discovery_busy(session) or agents.active_mission(session):
        return None, "already"
    now = utcnow()
    eligible = []
    for row in coverage(session, now):
        source = session.get(Source, row.id)
        assert source
        minimum = max(
            PROVIDER_MINUTES.get(source.source_type, 0),
            source_policy(source).refresh_interval_minutes or 0,
        )
        if row.state != "Checking" and (
            row.checked is None or now - row.checked >= timedelta(minutes=minimum)
        ):
            eligible.append(row.id)
    if not eligible:
        return None, "cooldown"
    mission, _ = agents.start_monitor_mission(session, eligible)
    return mission.id, "queued"
