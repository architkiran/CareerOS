from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import ActivityEvent, Task
from careeros.modules.scheduler import queue


def test_enqueue_idempotent_while_active(session: Session) -> None:
    a, created_a = queue.enqueue(session, "t", {"x": 1}, idempotency_key="k")
    b, created_b = queue.enqueue(session, "t", {"x": 2}, idempotency_key="k")
    assert created_a and not created_b and a.id == b.id
    session.commit()
    claimed = queue.claim(session, "w1")
    assert claimed is not None
    c, created_c = queue.enqueue(session, "t", idempotency_key="k")
    assert not created_c and c.id == a.id  # running counts as active
    queue.complete(session, claimed)
    session.commit()
    d, created_d = queue.enqueue(session, "t", idempotency_key="k")
    assert created_d and d.id != a.id  # finished tasks don't block reruns


def test_db_enforces_one_active_task_per_key(session: Session) -> None:
    session.add(Task(task_type="t", idempotency_key="dup"))
    session.commit()
    session.add(Task(task_type="t", idempotency_key="dup"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_claim_respects_priority_and_run_after(session: Session) -> None:
    queue.enqueue(session, "low", priority=200)
    queue.enqueue(session, "future", priority=1, run_after=utcnow() + timedelta(hours=1))
    queue.enqueue(session, "high", priority=10)
    session.commit()
    first = queue.claim(session, "w")
    second = queue.claim(session, "w")
    assert first is not None and second is not None
    assert (first.task_type, second.task_type) == ("high", "low")
    assert queue.claim(session, "w") is None  # future task not yet runnable


def test_claim_sets_lease_and_attempts(session: Session) -> None:
    queue.enqueue(session, "t")
    session.commit()
    task = queue.claim(session, "worker-a", lease_seconds=60)
    assert task is not None
    assert (task.status, task.attempts, task.locked_by) == ("running", 1, "worker-a")
    assert task.locked_until is not None and task.locked_until > utcnow()
    assert queue.claim(session, "worker-b") is None


def test_expired_lease_is_reclaimed(session: Session) -> None:
    queue.enqueue(session, "t")
    session.commit()
    task = queue.claim(session, "crashed-worker")
    assert task is not None
    task.locked_until = utcnow() - timedelta(seconds=1)
    session.commit()
    again = queue.claim(session, "worker-b")
    assert again is not None and again.id == task.id
    assert again.locked_by == "worker-b" and again.attempts == 2


def test_fail_retries_with_backoff_then_dead_letters(session: Session) -> None:
    queue.enqueue(session, "flaky", max_attempts=2)
    session.commit()
    task = queue.claim(session, "w")
    assert task is not None
    queue.fail(session, task, "boom 1")
    session.commit()
    assert task.status == "queued" and task.run_after > utcnow() + timedelta(seconds=20)
    task.run_after = utcnow() - timedelta(seconds=1)
    session.commit()
    task = queue.claim(session, "w")
    assert task is not None
    queue.fail(session, task, "boom 2")
    session.commit()
    assert task.status == "dead" and task.finished_at is not None and task.last_error == "boom 2"
    msgs = [
        e.message
        for e in session.scalars(
            select(ActivityEvent).where(ActivityEvent.event_type == "task.failed")
        )
    ]
    assert any("failed permanently" in m for m in msgs)
    assert [t.id for t in queue.dead_tasks(session)] == [task.id]


def test_retry_dead(session: Session) -> None:
    queue.enqueue(session, "t", max_attempts=1)
    session.commit()
    task = queue.claim(session, "w")
    assert task is not None
    queue.fail(session, task, "x")
    session.commit()
    queue.retry_dead(session, task.id)
    session.commit()
    assert (task.status, task.attempts) == ("queued", 0)
    with pytest.raises(LookupError):
        queue.retry_dead(session, task.id)  # no longer dead
    with pytest.raises(LookupError):
        queue.retry_dead(session, "missing")


def test_queue_stats(session: Session) -> None:
    queue.enqueue(session, "a")
    queue.enqueue(session, "b")
    session.commit()
    queue.claim(session, "w")
    stats = queue.queue_stats(session)
    assert (stats.queued, stats.running, stats.dead) == (1, 1, 0)
    assert stats.oldest_queued_at is not None and stats.oldest_queued_at.tzinfo is not None


def test_backoff_grows_and_caps() -> None:
    assert 30 <= queue.backoff_seconds(1) <= 45
    assert 60 <= queue.backoff_seconds(2) <= 90
    assert queue.backoff_seconds(20) == queue.BACKOFF_MAX_SECONDS


def test_long_error_truncated(session: Session) -> None:
    queue.enqueue(session, "t")
    session.commit()
    task = queue.claim(session, "w")
    assert task is not None
    queue.fail(session, task, "x" * 5000)
    assert task.last_error is not None and len(task.last_error) == 2000
