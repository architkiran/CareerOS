from datetime import timedelta
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from careeros.common.clock import utcnow
from careeros.db.models import ActivityEvent, AgentAttempt, AgentRun, Mission, Task
from careeros.modules.agents import service
from careeros.modules.agents.contracts import AgentOutput
from careeros.modules.agents.registry import TASK_TYPE
from careeros.modules.scheduler import queue
from careeros.modules.scheduler.worker import Worker
from careeros.modules.sources import registry
from tests.helpers import GH_URL, load_fixture, make_fetcher


@pytest.fixture
def factory(app: FastAPI) -> sessionmaker[Session]:
    return app.state.session_factory  # type: ignore[no-any-return]


def start(factory: sessionmaker[Session]) -> str:
    with factory() as session:
        mission, _ = service.start_mission(session)
        session.commit()
        return mission.id


def worker(factory: sessionmaker[Session], **kwargs: Any) -> Worker:
    return Worker(factory, fetcher_factory=lambda: make_fetcher(max_attempts=1), **kwargs)


def test_mission_deduplicates_and_handoffs_survive_restart(factory: sessionmaker[Session]) -> None:
    mission_id = start(factory)
    with factory() as session:
        duplicate, created = service.start_mission(session)
        assert not created and duplicate.id == mission_id
        assert [r.status for r in service.runs_for(session, mission_id)] == [
            "queued",
            "blocked",
            "blocked",
            "blocked",
            "blocked",
        ]
        session.commit()
    for n in range(5):
        # A fresh worker simulates restart between every persisted handoff.
        assert worker(factory).run_once()
        with factory() as session:
            runs = service.runs_for(session, mission_id)
            assert sum(r.status == "succeeded" for r in runs) == n + 1
    assert not worker(factory).run_once()
    with factory() as session:
        mission = session.get(Mission, mission_id)
        assert mission and mission.status == "degraded"  # missing setup is honest, not green
        assert mission.started_at and mission.finished_at
        assert len(session.scalars(select(AgentAttempt)).all()) == 5
        assert all(a.status == "succeeded" for a in session.scalars(select(AgentAttempt)))
        assert len(session.scalars(select(Task)).all()) == 5
        assert service.runs_for(session, mission_id)[0].result_json["warnings"]
        assert "mission.handoff" in session.scalars(select(ActivityEvent.event_type)).all()


@respx.mock
def test_real_discovery_matching_pipeline(
    factory: sessionmaker[Session], client: TestClient
) -> None:
    from careeros.modules.profile import service as profile
    from careeros.modules.profile.schemas import ProfileIn, SkillIn

    with factory() as session:
        registry.add_source(
            session, registry.SourceIn(type="greenhouse", token="examplepay", name="ExamplePay")
        )
        profile.update_profile(session, ProfileIn(display_name="Candidate"))
        profile.add_default_lanes(session)
        profile.add_skill(session, SkillIn(name="SQL", verified_status="verified"))
        session.commit()
    respx.get(GH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("greenhouse_jobs.json"))
    )
    mission_id = start(factory)
    for _ in range(5):
        assert worker(factory).run_once()
    with factory() as session:
        runs = service.runs_for(session, mission_id)
        assert runs[0].result_json["metrics"]["new_jobs"] == 3
        assert runs[1].result_json["metrics"]["jobs"] == 3
        assert runs[1].result_json["metrics"]["scored"] > 0
        assert runs[3].result_json["metrics"]["discovered"] == 3
        assert all(r.status == "succeeded" for r in runs)
    populated = client.get("/mission-control")
    assert populated.status_code == 200
    assert "ExamplePay" in populated.text and "Source date:" in populated.text
    assert "First seen:" in populated.text and "Last source refresh" in populated.text


@respx.mock
def test_source_failure_blocks_handoff_and_manual_retry_keeps_attempts(
    factory: sessionmaker[Session],
) -> None:
    with factory() as session:
        registry.add_source(
            session, registry.SourceIn(type="greenhouse", token="examplepay", name="ExamplePay")
        )
        session.commit()
    source = respx.get(GH_URL).mock(return_value=httpx.Response(500))
    mission_id = start(factory)
    for _ in range(3):
        assert worker(factory).run_once()
        with factory() as session:
            task = session.scalars(select(Task)).one()
            task.run_after = utcnow() - timedelta(seconds=1)
            session.commit()
    with factory() as session:
        mission = session.get(Mission, mission_id)
        assert mission and mission.status == "failed"
        runs = service.runs_for(session, mission_id)
        assert [r.status for r in runs] == ["failed", "blocked", "blocked", "blocked", "blocked"]
        assert "All configured feeds failed" in (runs[0].last_error or "")
        run_id = runs[0].id
        service.retry_run(session, run_id)
        session.commit()
    source.mock(return_value=httpx.Response(200, json=load_fixture("greenhouse_jobs.json")))
    assert worker(factory).run_once()
    with factory() as session:
        attempts = list(session.scalars(select(AgentAttempt).order_by(AgentAttempt.number)))
        assert [a.number for a in attempts] == [1, 2, 3, 4]
        assert [a.status for a in attempts] == ["failed", "failed", "failed", "succeeded"]
        assert service.runs_for(session, mission_id)[1].status == "queued"
        with pytest.raises(service.MissionConflict):
            service.retry_run(session, run_id)


def test_pause_resume_cancel_controls(factory: sessionmaker[Session]) -> None:
    mission_id = start(factory)
    with factory() as session:
        service.control_mission(session, mission_id, "pause")
        session.commit()
        assert service.start_mission(session)[1] is False
    assert not worker(factory).run_once()
    with factory() as session:
        service.control_mission(session, mission_id, "resume")
        session.commit()
    assert worker(factory).run_once()
    with factory() as session:
        service.control_mission(session, mission_id, "cancel")
        session.commit()
        runs = service.runs_for(session, mission_id)
        assert runs[0].status == "succeeded"
        assert all(r.status == "cancelled" for r in runs[1:])
        with pytest.raises(service.MissionConflict):
            service.control_mission(session, mission_id, "resume")
    assert not worker(factory).run_once()


def test_pause_during_execution_stops_next_handoff(factory: sessionmaker[Session]) -> None:
    mission_id = start(factory)

    def pause(*_args: object) -> dict[str, Any]:
        with factory() as session:
            service.control_mission(session, mission_id, "pause")
            session.commit()
        return AgentOutput(summary="Checked feeds.").model_dump()

    worker(factory, handlers={TASK_TYPE: pause}).run_once()
    with factory() as session:
        assert service.runs_for(session, mission_id)[1].status == "blocked"
        service.control_mission(session, mission_id, "resume")
        session.commit()
        assert service.runs_for(session, mission_id)[1].status == "queued"


def test_crash_reclaim_fences_old_owner_and_records_interrupted_attempt(
    factory: sessionmaker[Session],
) -> None:
    mission_id = start(factory)
    with factory() as session:
        task = queue.claim(session, "crashed")
        assert task
        service.begin_task(session, task)
        old_attempt = task.attempts
        task.locked_until = utcnow() - timedelta(seconds=1)
        task_id = task.id
        session.commit()
    assert worker(factory).run_once()
    with factory() as session:
        assert not queue.renew_lease(session, task_id, "crashed", old_attempt)
        attempts = list(session.scalars(select(AgentAttempt).order_by(AgentAttempt.number)))
        assert [a.status for a in attempts] == ["interrupted", "succeeded"]
        assert service.runs_for(session, mission_id)[1].status == "queued"


def test_failure_metadata_does_not_leak_private_input(factory: sessionmaker[Session]) -> None:
    mission_id = start(factory)

    def broken(*_args: object) -> None:
        raise ValueError("PRIVATE RESUME TEXT: credentials and authorization")

    worker(factory, handlers={TASK_TYPE: broken}).run_once()
    with factory() as session:
        run = service.runs_for(session, mission_id)[0]
        assert run.status == "retrying" and "ValueError" in (run.last_error or "")
        assert "PRIVATE RESUME" not in str(run.last_error)
        assert all(
            "PRIVATE RESUME" not in e.message for e in session.scalars(select(ActivityEvent))
        )


def test_mission_schedule_deduplicates_and_waits_for_interval(
    factory: sessionmaker[Session],
) -> None:
    now = utcnow()
    with factory() as session:
        assert service.maybe_schedule(session, 1, now)
        assert not service.maybe_schedule(session, 1, now + timedelta(minutes=30))
        mission = session.scalars(select(Mission)).one()
        service.control_mission(session, mission.id, "cancel")
        session.commit()
        assert service.maybe_schedule(session, 1, now + timedelta(hours=2))


def test_retry_refuses_when_newer_mission_active(factory: sessionmaker[Session]) -> None:
    mission_id = start(factory)
    with factory() as session:
        run = service.runs_for(session, mission_id)[0]
        task = session.get(Task, run.task_id)
        assert task
        task.status, run.status = "dead", "failed"
        mission = session.get(Mission, mission_id)
        assert mission
        mission.status = "failed"
        session.commit()
        service.start_mission(session)
        session.commit()
        with pytest.raises(service.MissionConflict, match="active career review"):
            service.retry_run(session, run.id)


def test_mission_start_rollback_does_not_leave_partial_mission(
    factory: sessionmaker[Session],
) -> None:
    with factory() as session:
        service.start_mission(session)
        session.rollback()
    with factory() as session:
        assert session.scalars(select(Mission)).all() == []
        assert session.scalars(select(AgentRun)).all() == []
        assert session.scalars(select(Task)).all() == []


def test_concurrent_mission_start_creates_one_graph(factory: sessionmaker[Session]) -> None:
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _n: start(factory), range(2)))
    assert ids[0] == ids[1]
    with factory() as session:
        assert len(session.scalars(select(Mission)).all()) == 1
        assert len(session.scalars(select(AgentRun)).all()) == 5
        assert len(session.scalars(select(Task)).all()) == 1


def test_cancel_inflight_execution_stops_downstream(factory: sessionmaker[Session]) -> None:
    mission_id = start(factory)

    def cancel(*_args: object) -> dict[str, Any]:
        with factory() as session:
            service.control_mission(session, mission_id, "cancel")
            session.commit()
        return AgentOutput(summary="Read finished after cancellation.").model_dump()

    worker(factory, handlers={TASK_TYPE: cancel}).run_once()
    assert not worker(factory).run_once()
    with factory() as session:
        assert session.get(Mission, mission_id).status == "cancelled"
        assert all(r.status == "cancelled" for r in service.runs_for(session, mission_id))
        assert session.scalars(select(Task)).one().status == "cancelled"


def test_invalid_agent_output_retries_instead_of_becoming_success(
    factory: sessionmaker[Session],
) -> None:
    mission_id = start(factory)
    worker(factory, handlers={TASK_TYPE: lambda *_a: {"unexpected": "data"}}).run_once()
    with factory() as session:
        assert service.runs_for(session, mission_id)[0].status == "retrying"
        assert service.runs_for(session, mission_id)[1].status == "blocked"


def test_expired_owner_cannot_complete_after_new_attempt(factory: sessionmaker[Session]) -> None:
    start(factory)
    with factory() as session:
        first = queue.claim(session, "same-worker")
        assert first
        task_id, attempt = first.id, first.attempts
        assert queue.renew_lease(session, task_id, "same-worker", attempt)
        first.locked_until = utcnow() - timedelta(seconds=1)
        session.commit()
    with factory() as session:
        assert queue.claim(session, "same-worker")
        assert not queue.renew_lease(session, task_id, "same-worker", attempt)


@respx.mock
def test_healthy_review_succeeds_and_preserves_verified_profile(
    factory: sessionmaker[Session],
) -> None:
    from careeros.modules.profile import service as profile
    from careeros.modules.profile.schemas import ProfileIn, SkillIn, WorkAuthorizationIn

    with factory() as session:
        registry.add_source(
            session, registry.SourceIn(type="greenhouse", token="examplepay", name="ExamplePay")
        )
        profile.update_profile(session, ProfileIn(display_name="Test Candidate"))
        profile.add_skill(session, SkillIn(name="SQL", verified_status="verified"))
        profile.add_default_lanes(session)
        profile.save_work_authorization(session, WorkAuthorizationIn(confirmed=True))
        session.commit()
        before = profile.export_profile(session).model_dump(exclude={"exported_at"})
    # Only a valid posting: the general fixture deliberately contains one invalid item.
    raw = load_fixture("greenhouse_jobs.json")
    raw["jobs"] = raw["jobs"][:1]
    respx.get(GH_URL).mock(return_value=httpx.Response(200, json=raw))
    mission_id = start(factory)
    for _ in range(5):
        assert worker(factory).run_once()
    with factory() as session:
        assert session.get(Mission, mission_id).status == "succeeded"
        assert profile.export_profile(session).model_dump(exclude={"exported_at"}) == before
        assert all(not r.result_json["warnings"] for r in service.runs_for(session, mission_id))
