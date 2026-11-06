"""Task handlers, the local scheduler, and the worker loop."""

import logging
import socket
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from careeros.common.clock import utcnow
from careeros.db.models import PipelineRun
from careeros.modules.agents import service as agents
from careeros.modules.agents.contracts import AgentExecutionError, AgentOutput
from careeros.modules.agents.execution import execute as execute_agent
from careeros.modules.agents.registry import TASK_TYPE
from careeros.modules.events.service import record_event
from careeros.modules.ingestion.service import RunSummary, run_all
from careeros.modules.scheduler import queue
from careeros.modules.sources.http import Fetcher
from careeros.modules.system.settings_store import get_setting, set_setting

logger = logging.getLogger(__name__)

DISCOVERY = "discovery"
LAST_SCHEDULED_KEY = "scheduler.last_enqueued_at"

Handler = Callable[
    [sessionmaker[Session], dict[str, Any], Callable[[], Fetcher]], dict[str, Any] | None
]


def _discovery(
    factory: sessionmaker[Session],
    source_ids: list[str] | None,
    trigger: str,
    fetcher_factory: Callable[[], Fetcher],
) -> None:
    with factory() as session:
        run = PipelineRun(pipeline_name=DISCOVERY, trigger=trigger)
        session.add(run)
        session.commit()
        run_id = run.id
    fetcher = fetcher_factory()
    try:
        results: list[RunSummary] = run_all(factory, fetcher, source_ids=source_ids)
    finally:
        fetcher.close()
    counters = {
        "sources": len(results),
        "failed_sources": sum(1 for r in results if r.status == "failed"),
        "fetched": sum(r.fetched for r in results),
        "new": sum(r.new for r in results),
        "updated": sum(r.updated for r in results),
        "duplicates": sum(r.duplicates for r in results),
        "invalid": sum(r.invalid for r in results),
        "closed": sum(r.closed for r in results),
    }
    if not results:
        status = "success"
    elif counters["failed_sources"] == len(results):
        status = "failed"
    elif counters["failed_sources"] or counters["invalid"]:
        status = "partial"
    else:
        status = "success"
    with factory() as session:
        finished = session.get(PipelineRun, run_id)
        assert finished is not None
        run = finished
        run.status = status
        run.finished_at = utcnow()
        run.counters_json = counters
        run.error_summary = (
            "; ".join(f"{r.source_name}: {r.error}" for r in results if r.error)[:2000] or None
        )
        record_event(
            session,
            "run.completed",
            f"Discovery {status}: {counters['new']} new jobs from {counters['sources']} sources"
            + (f", {counters['failed_sources']} failed" if counters["failed_sources"] else ""),
            entity_type="pipeline_run",
            entity_id=run_id,
            metadata=counters,
        )
        if counters["new"] or counters["updated"] or counters["closed"]:
            enqueue_rescore(session, "new jobs")
        session.commit()


def handle_ingest_all(
    factory: sessionmaker[Session], payload: dict[str, Any], fetcher_factory: Callable[[], Fetcher]
) -> None:
    _discovery(factory, None, str(payload.get("trigger", "manual")), fetcher_factory)


def handle_ingest_source(
    factory: sessionmaker[Session], payload: dict[str, Any], fetcher_factory: Callable[[], Fetcher]
) -> None:
    source_id = payload.get("source_id")
    if not isinstance(source_id, str):
        raise ValueError("ingest.source requires source_id")
    _discovery(factory, [source_id], "manual", fetcher_factory)


def handle_match_all(
    factory: sessionmaker[Session], payload: dict[str, Any], fetcher_factory: Callable[[], Fetcher]
) -> None:
    from careeros.modules.matching.service import score_jobs

    with factory() as session:
        score_jobs(session, commit_every=25)
        session.commit()


HANDLERS: dict[str, Handler] = {
    TASK_TYPE: execute_agent,
    "ingest.all": handle_ingest_all,
    "ingest.source": handle_ingest_source,
    "match.all": handle_match_all,
}


def enqueue_rescore(session: Session, reason: str) -> tuple[Any, bool]:
    """Queue a rescoring pass. Unchanged job/lane/profile inputs are skipped, so this is cheap."""
    task, created = queue.enqueue(
        session, "match.all", {"reason": reason}, idempotency_key="match.all", priority=50
    )
    if created:
        record_event(
            session,
            "task.queued",
            f"Rescoring queued ({reason})",
            entity_type="task",
            entity_id=task.id,
        )
    return task, created


def enqueue_discovery(session: Session, trigger: str = "manual") -> tuple[Any, bool]:
    task, created = queue.enqueue(
        session, "ingest.all", {"trigger": trigger}, idempotency_key="ingest.all"
    )
    if created:
        record_event(
            session,
            "task.queued",
            f"Discovery run queued ({trigger})",
            entity_type="task",
            entity_id=task.id,
        )
    return task, created


def enqueue_source(session: Session, source_id: str, name: str) -> tuple[Any, bool]:
    task, created = queue.enqueue(
        session,
        "ingest.source",
        {"source_id": source_id},
        idempotency_key=f"ingest.source:{source_id}",
    )
    if created:
        record_event(
            session, "task.queued", f"Fetch queued: {name}", entity_type="task", entity_id=task.id
        )
    return task, created


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def maybe_schedule(session: Session, interval_hours: float, now: datetime | None = None) -> bool:
    """Queue a discovery run if the interval has elapsed. Returns True if queued."""
    now = now or utcnow()
    last = _parse(get_setting(session, LAST_SCHEDULED_KEY))
    if last is not None and now - last < timedelta(hours=interval_hours):
        return False
    _, created = enqueue_discovery(session, "schedule")
    set_setting(session, LAST_SCHEDULED_KEY, now.isoformat())
    session.commit()
    return created


def last_discovery(session: Session, *, successful: bool = False) -> PipelineRun | None:
    stmt = select(PipelineRun).where(PipelineRun.pipeline_name == DISCOVERY)
    if successful:
        stmt = stmt.where(PipelineRun.status.in_(("success", "partial")))
    return session.scalars(stmt.order_by(PipelineRun.started_at.desc()).limit(1)).first()


def schedule_overdue(session: Session, interval_hours: float, now: datetime | None = None) -> bool:
    """True when the last successful discovery is older than 1.5x the interval (e.g. Mac slept)."""
    now = now or utcnow()
    last = last_discovery(session, successful=True)
    reference = last.finished_at if last and last.finished_at else None
    if reference is None:
        return False
    return now - reference > timedelta(hours=interval_hours * 1.5)


class Worker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        scheduler_enabled: bool = False,
        mission_scheduler_enabled: bool = False,
        schedule_interval_hours: float = 24,
        poll_seconds: float = 2.0,
        fetcher_factory: Callable[[], Fetcher] = Fetcher,
        handlers: dict[str, Handler] | None = None,
    ) -> None:
        self.factory = factory
        self.scheduler_enabled = scheduler_enabled
        self.mission_scheduler_enabled = mission_scheduler_enabled
        self.schedule_interval_hours = schedule_interval_hours
        self.poll_seconds = poll_seconds
        self.fetcher_factory = fetcher_factory
        self.handlers = handlers or HANDLERS
        self.worker_id = f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def ensure_current_scores(self) -> None:
        """Queue a rescore once at startup if the matching algorithm changed."""
        from careeros.modules.matching.service import has_stale_scores

        with self.factory() as session:
            if has_stale_scores(session):
                enqueue_rescore(session, "matching algorithm updated")
                session.commit()

    def _heartbeat(self, stop: threading.Event, task_id: str, attempt: int) -> None:
        while not stop.wait(30):
            try:
                with self.factory() as session:
                    renewed = queue.renew_lease(session, task_id, self.worker_id, attempt)
                    if renewed:
                        set_setting(session, "worker.last_seen_at", utcnow().isoformat())
                    session.commit()
                if not renewed:
                    return
            except Exception:
                logger.warning("Could not renew task lease %s", task_id)

    def run_once(self) -> bool:
        """Schedule if due, then execute at most one bounded task with a renewable lease."""
        with self.factory() as session:
            set_setting(session, "worker.last_seen_at", utcnow().isoformat())
            session.commit()
            if self.scheduler_enabled:
                maybe_schedule(session, self.schedule_interval_hours)
            if self.mission_scheduler_enabled:
                agents.maybe_schedule(session, self.schedule_interval_hours)
            task = queue.claim(session, self.worker_id)
            if task is None:
                return False
            task_id, attempt = task.id, task.attempts
            is_agent = task.task_type == TASK_TYPE
            agents.begin_task(session, task)
            session.commit()
            handler = self.handlers.get(task.task_type)
            stop = threading.Event()
            heartbeat = threading.Thread(
                target=self._heartbeat, args=(stop, task_id, attempt), daemon=True
            )
            heartbeat.start()
            result = None
            error = None
            try:
                if task.attempts > task.max_attempts:
                    raise AgentExecutionError(
                        "Worker lease expired too many times. Retry this step."
                    )
                if handler is None:
                    raise ValueError(f"No handler for task type {task.task_type!r}")
                result = handler(self.factory, dict(task.payload_json), self.fetcher_factory)
                if is_agent:
                    result = AgentOutput.model_validate(result).model_dump()
            except Exception as exc:
                if is_agent:
                    # Untrusted input and candidate values must not escape into operational logs.
                    logger.error("Agent task %s failed (%s)", task_id, type(exc).__name__)
                    error = (
                        str(exc)
                        if isinstance(exc, AgentExecutionError)
                        else (
                            f"{type(exc).__name__}: Agent execution failed. "
                            "Check configuration and retry."
                        )
                    )
                else:
                    logger.exception("Task %s (%s) failed", task_id, task.task_type)
                    error = f"{type(exc).__name__}: {exc}"
            finally:
                stop.set()
                heartbeat.join(timeout=5)
            session.rollback()
            if not queue.renew_lease(session, task_id, self.worker_id, attempt):
                session.rollback()
                logger.warning("Discarding completion from expired owner of task %s", task_id)
                return True
            fresh = session.get(queue.Task, task_id, populate_existing=True)
            assert fresh is not None
            if error:
                queue.fail(session, fresh, error)
                agents.finish_task(session, fresh, error=error)
            else:
                queue.complete(session, fresh)
                agents.finish_task(session, fresh, result=result)
            session.commit()
            return True

    def _loop(self) -> None:
        logger.info("Worker %s started", self.worker_id)
        try:
            self.ensure_current_scores()
        except Exception:
            logger.exception("Could not check for stale scores")
        while not self._stop.is_set():
            try:
                ran = self.run_once()
            except Exception:
                logger.exception("Worker loop error")
                ran = False
            if not ran:
                self._stop.wait(self.poll_seconds)
        logger.info("Worker %s stopped", self.worker_id)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="careeros-worker", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
