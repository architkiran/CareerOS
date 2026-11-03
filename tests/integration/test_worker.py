import time
from datetime import timedelta
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from careeros.common.clock import utcnow
from careeros.db.models import ActivityEvent, PipelineRun, Task
from careeros.modules.scheduler import queue
from careeros.modules.scheduler.worker import (
    LAST_SCHEDULED_KEY,
    Worker,
    enqueue_discovery,
    enqueue_source,
    maybe_schedule,
    schedule_overdue,
)
from careeros.modules.sources import registry
from careeros.modules.system.settings_store import get_setting
from tests.helpers import GH_URL, LEVER_URL, load_fixture, make_fetcher


@pytest.fixture
def factory(app: FastAPI) -> sessionmaker[Session]:
    return app.state.session_factory  # type: ignore[no-any-return]


def _worker(factory: sessionmaker[Session], **kw: Any) -> Worker:
    return Worker(factory, fetcher_factory=lambda: make_fetcher(max_attempts=1), **kw)


def _add(factory: sessionmaker[Session], type_: str, token: str, name: str) -> str:
    with factory() as s:
        src = registry.add_source(s, registry.SourceIn(type=type_, token=token, name=name))  # type: ignore[arg-type]
        s.commit()
        return src.id


def test_idle_worker_does_nothing(factory: sessionmaker[Session]) -> None:
    assert _worker(factory).run_once() is False


@respx.mock
def test_discovery_task_runs_pipeline(factory: sessionmaker[Session]) -> None:
    _add(factory, "greenhouse", "examplepay", "ExamplePay")
    _add(factory, "lever", "examplebank", "ExampleBank")
    respx.get(GH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("greenhouse_jobs.json"))
    )
    respx.get(LEVER_URL).mock(return_value=httpx.Response(500))
    with factory() as s:
        enqueue_discovery(s)
        s.commit()
    assert _worker(factory).run_once() is True
    with factory() as s:
        run = s.scalars(select(PipelineRun)).one()
        assert run.status == "partial" and run.finished_at is not None
        assert run.counters_json["new"] == 3 and run.counters_json["failed_sources"] == 1
        assert "ExampleBank" in (run.error_summary or "")
        tasks = {t.task_type: t for t in s.scalars(select(Task))}
        assert tasks["ingest.all"].status == "succeeded"
        assert tasks["match.all"].status == "queued"  # new jobs trigger rescoring
        types = [e.event_type for e in s.scalars(select(ActivityEvent))]
        assert "task.queued" in types and "run.completed" in types


@respx.mock
def test_all_sources_failing_marks_run_failed(factory: sessionmaker[Session]) -> None:
    _add(factory, "lever", "examplebank", "ExampleBank")
    respx.get(LEVER_URL).mock(return_value=httpx.Response(404))
    with factory() as s:
        enqueue_discovery(s)
        s.commit()
    _worker(factory).run_once()
    with factory() as s:
        assert s.scalars(select(PipelineRun)).one().status == "failed"


@respx.mock
def test_single_source_task(factory: sessionmaker[Session]) -> None:
    gh = _add(factory, "greenhouse", "examplepay", "ExamplePay")
    _add(factory, "lever", "examplebank", "ExampleBank")
    respx.get(GH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("greenhouse_jobs.json"))
    )
    lever = respx.get(LEVER_URL).mock(return_value=httpx.Response(200, json=[]))
    with factory() as s:
        _, created = enqueue_source(s, gh, "ExamplePay")
        _, again = enqueue_source(s, gh, "ExamplePay")
        s.commit()
    assert created and not again
    _worker(factory).run_once()
    assert lever.call_count == 0  # only the requested source ran


def test_handler_error_retries_then_dead(factory: sessionmaker[Session]) -> None:
    def broken(*_a: object) -> None:
        raise RuntimeError("handler bug")

    w = Worker(factory, handlers={"broken": broken})
    with factory() as s:
        queue.enqueue(s, "broken", max_attempts=2)
        s.commit()
    w.run_once()
    with factory() as s:
        task = s.scalars(select(Task)).one()
        assert task.status == "queued" and "handler bug" in (task.last_error or "")
        task.run_after = utcnow() - timedelta(seconds=1)
        s.commit()
    w.run_once()
    with factory() as s:
        assert s.scalars(select(Task)).one().status == "dead"


def test_unknown_task_type_dead_letters(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        queue.enqueue(s, "nonexistent", max_attempts=1)
        s.commit()
    _worker(factory).run_once()
    with factory() as s:
        task = s.scalars(select(Task)).one()
        assert task.status == "dead" and "No handler" in (task.last_error or "")


def test_ingest_source_without_id_fails(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        queue.enqueue(s, "ingest.source", {}, max_attempts=1)
        s.commit()
    _worker(factory).run_once()
    with factory() as s:
        assert s.scalars(select(Task)).one().status == "dead"


def test_scheduler_queues_once_per_interval(factory: sessionmaker[Session]) -> None:
    now = utcnow()
    with factory() as s:
        assert maybe_schedule(s, 24, now) is True
        assert get_setting(s, LAST_SCHEDULED_KEY) == now.isoformat()
        assert maybe_schedule(s, 24, now + timedelta(hours=1)) is False
        task = s.scalars(select(Task)).one()
        queue.claim(s, "w")
        queue.complete(s, s.get(Task, task.id))  # type: ignore[arg-type]
        s.commit()
        assert maybe_schedule(s, 24, now + timedelta(hours=25)) is True
        assert len(s.scalars(select(Task)).all()) == 2


def test_worker_with_scheduler_disabled_does_not_schedule(factory: sessionmaker[Session]) -> None:
    _worker(factory, scheduler_enabled=False).run_once()
    with factory() as s:
        assert s.scalars(select(Task)).all() == []


def test_worker_with_scheduler_enabled_schedules_and_runs(factory: sessionmaker[Session]) -> None:
    assert _worker(factory, scheduler_enabled=True).run_once() is True
    with factory() as s:
        run = s.scalars(select(PipelineRun)).one()
        assert run.trigger == "schedule" and run.status == "success"  # no sources is fine


def test_schedule_overdue(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        assert schedule_overdue(s, 24) is False  # never ran: nothing to be overdue against
        s.add(
            PipelineRun(
                pipeline_name="discovery",
                status="success",
                started_at=utcnow() - timedelta(hours=40),
                finished_at=utcnow() - timedelta(hours=40),
            )
        )
        s.commit()
        assert schedule_overdue(s, 24) is True
        assert schedule_overdue(s, 48) is False


def test_worker_thread_processes_and_stops(factory: sessionmaker[Session]) -> None:
    done: list[str] = []
    w = Worker(factory, poll_seconds=0.05, handlers={"noop": lambda *_a: done.append("x")})
    with factory() as s:
        queue.enqueue(s, "noop")
        s.commit()
    w.start()
    deadline = time.monotonic() + 5
    while not done and time.monotonic() < deadline:
        time.sleep(0.02)
    w.stop()
    assert done == ["x"]
    with factory() as s:
        assert s.scalars(select(Task)).one().status == "succeeded"
