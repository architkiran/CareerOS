"""SQLite task queue with leases, retries with backoff, and dead-lettering.

A worker claims a task with a conditional UPDATE, so two workers can never
own the same task. A crashed worker's lease expires and the task is reclaimed.
Handlers must be idempotent.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import Task

__all__ = ["Task"]
from careeros.modules.events.service import record_event

QUEUED, RUNNING, SUCCEEDED, DEAD = "queued", "running", "succeeded", "dead"
BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 3600


def enqueue(
    session: Session,
    task_type: str,
    payload: dict[str, Any] | None = None,
    *,
    idempotency_key: str | None = None,
    priority: int = 100,
    max_attempts: int = 3,
    run_after: datetime | None = None,
) -> tuple[Task, bool]:
    """Queue a task. Returns (task, created). An active task with the same key is reused."""
    if idempotency_key:
        existing = session.scalars(
            select(Task).where(
                Task.idempotency_key == idempotency_key, Task.status.in_((QUEUED, RUNNING))
            )
        ).first()
        if existing is not None:
            return existing, False
    task = Task(
        task_type=task_type,
        payload_json=payload or {},
        idempotency_key=idempotency_key,
        priority=priority,
        max_attempts=max_attempts,
        run_after=run_after or utcnow(),
    )
    try:
        with session.begin_nested():
            session.add(task)
    except IntegrityError:  # lost a race with another enqueuer
        existing = session.scalars(
            select(Task).where(
                Task.idempotency_key == idempotency_key, Task.status.in_((QUEUED, RUNNING))
            )
        ).one()
        return existing, False
    return task, True


def claim(session: Session, worker_id: str, lease_seconds: int = 600) -> Task | None:
    """Claim the next runnable task (or one whose lease expired). Commits."""
    now = utcnow()
    for _ in range(5):
        candidate = session.scalars(
            select(Task)
            .where(
                ((Task.status == QUEUED) & (Task.run_after <= now))
                | ((Task.status == RUNNING) & (Task.locked_until < now))
            )
            .order_by(Task.priority, Task.run_after, Task.created_at)
            .limit(1)
        ).first()
        if candidate is None:
            return None
        prev_status, prev_lock = candidate.status, candidate.locked_until
        stmt = (
            update(Task)
            .where(Task.id == candidate.id, Task.status == prev_status)
            .where(
                Task.locked_until.is_(None) if prev_lock is None else Task.locked_until == prev_lock
            )
            .values(
                status=RUNNING,
                locked_by=worker_id,
                locked_until=now + timedelta(seconds=lease_seconds),
                attempts=Task.attempts + 1,
                started_at=now,
            )
        )
        if session.execute(stmt).rowcount == 1:  # type: ignore[attr-defined]
            session.commit()
            session.refresh(candidate)
            return candidate
        session.rollback()  # someone else won; try the next one
    return None


def complete(session: Session, task: Task) -> None:
    task.status = SUCCEEDED
    task.finished_at = utcnow()
    task.locked_by = task.locked_until = None
    task.last_error = None


def backoff_seconds(attempt: int) -> float:
    base = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
    return float(min(base + random.uniform(0, base / 2), BACKOFF_MAX_SECONDS))  # noqa: S311


def fail(session: Session, task: Task, error: str) -> None:
    """Record a failure: retry later with backoff, or dead-letter when out of attempts."""
    task.last_error = error[:2000]
    task.locked_by = task.locked_until = None
    if task.attempts >= task.max_attempts:
        task.status = DEAD
        task.finished_at = utcnow()
        record_event(
            session,
            "task.failed",
            f"Task {task.task_type} failed permanently after {task.attempts} attempts: "
            f"{error[:200]}",
            entity_type="task",
            entity_id=task.id,
        )
    else:
        task.status = QUEUED
        task.run_after = utcnow() + timedelta(seconds=backoff_seconds(task.attempts))
        record_event(
            session,
            "task.retrying",
            f"Task {task.task_type} failed (attempt {task.attempts}), will retry: {error[:200]}",
            entity_type="task",
            entity_id=task.id,
        )


def retry_dead(session: Session, task_id: str) -> Task:
    task = session.get(Task, task_id)
    if task is None or task.status != DEAD:
        raise LookupError("No dead task with that id")
    task.status = QUEUED
    task.attempts = 0
    task.run_after = utcnow()
    task.finished_at = None
    record_event(
        session,
        "task.requeued",
        f"Task {task.task_type} requeued by user",
        entity_type="task",
        entity_id=task.id,
    )
    return task


@dataclass
class QueueStats:
    queued: int
    running: int
    dead: int
    oldest_queued_at: datetime | None


def queue_stats(session: Session) -> QueueStats:
    counts = dict(session.execute(select(Task.status, func.count()).group_by(Task.status)).all())
    oldest = session.scalar(select(func.min(Task.created_at)).where(Task.status == QUEUED))
    if oldest is not None and oldest.tzinfo is None:
        from datetime import UTC

        oldest = oldest.replace(tzinfo=UTC)
    return QueueStats(counts.get(QUEUED, 0), counts.get(RUNNING, 0), counts.get(DEAD, 0), oldest)


def dead_tasks(session: Session, limit: int = 20) -> list[Task]:
    stmt = select(Task).where(Task.status == DEAD).order_by(Task.finished_at.desc()).limit(limit)
    return list(session.scalars(stmt))


def active_task_keys(session: Session) -> set[str]:
    stmt = select(Task.idempotency_key).where(
        Task.status.in_((QUEUED, RUNNING)), Task.idempotency_key.is_not(None)
    )
    return {k for k in session.scalars(stmt) if k}
