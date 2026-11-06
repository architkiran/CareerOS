from datetime import timedelta

import httpx
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import AgentRun, SourceRun, Task
from careeros.modules.agents import service as agents
from careeros.modules.scheduler.worker import Worker
from careeros.modules.sources import registry
from careeros.modules.system.settings_store import set_setting
from tests.conftest import post_form
from tests.helpers import GH_URL, LEVER_URL, load_fixture, make_fetcher


def test_policy_validation_and_due_sources(session: Session) -> None:
    now = utcnow()
    source = registry.add_source(
        session,
        registry.SourceIn(
            type="greenhouse", token="test", name="Test", refresh_interval_minutes=60
        ),
    )
    source.last_success_at = now
    session.commit()
    assert registry.due_source_ids(session, now + timedelta(minutes=30)) == []
    assert registry.due_source_ids(session, now + timedelta(minutes=60)) == [source.id]
    # A recent failure still counts as an attempt, so a failing feed is not hammered.
    session.add(
        SourceRun(source_id=source.id, started_at=now + timedelta(minutes=50), status="failed")
    )
    session.commit()
    assert registry.due_source_ids(session, now + timedelta(minutes=60)) == []
    registry.set_source_policy(session, source.id, registry.SourcePolicy(rate_limit_seconds=3))
    session.commit()
    assert registry.due_source_ids(session, now + timedelta(minutes=60)) == [source.id]
    source.enabled = False
    session.commit()
    assert registry.due_source_ids(session, now + timedelta(days=2)) == []


def test_policy_forms_and_target_coverage(session: Session, client: TestClient) -> None:
    source = registry.add_source(
        session, registry.SourceIn(type="greenhouse", token="test", name="Test")
    )
    set_setting(session, "career.preferences", {"target_companies": ["Test", "Not connected"]})
    session.commit()
    assert client.post(f"/sources/{source.id}/policy").status_code == 403
    assert (
        post_form(
            client, f"/sources/{source.id}/policy", {"refresh_interval_minutes": "5"}
        ).status_code
        == 422
    )
    assert (
        post_form(
            client,
            f"/sources/{source.id}/policy",
            {"refresh_interval_minutes": "30", "rate_limit_seconds": "3"},
        ).status_code
        == 303
    )
    page = client.get("/sources").text
    assert "1 of 2 target employers" in page and "official careers-page research needed" in page
    assert post_form(client, "/sources/missing/policy", {}).status_code == 404


def test_scheduled_scope_is_frozen_in_task_payload(app: FastAPI, session: Session) -> None:
    source = registry.add_source(
        session,
        registry.SourceIn(
            type="greenhouse", token="examplepay", name="Example", refresh_interval_minutes=60
        ),
    )
    source.last_success_at = utcnow()
    session.commit()
    mission, _ = agents.start_mission(session, "schedule")
    session.commit()
    run = agents.runs_for(session, mission.id)[0]
    task = session.get(Task, run.task_id)
    assert task and task.payload_json["source_ids"] == []

    def no_network():  # type: ignore[no-untyped-def]
        raise AssertionError("A feed inside its minimum gap must not be requested")

    assert Worker(app.state.session_factory, fetcher_factory=no_network).run_once()
    session.expire_all()
    run = session.get(AgentRun, run.id)
    assert run.status == "succeeded" and "No feeds are due" in run.summary


@respx.mock
def test_cancellation_stops_discovery_between_sources(app: FastAPI, session: Session) -> None:
    registry.add_source(session, registry.SourceIn(type="greenhouse", token="examplepay", name="A"))
    registry.add_source(session, registry.SourceIn(type="lever", token="examplebank", name="B"))
    mission, _ = agents.start_mission(session)
    session.commit()

    def first_response(request: httpx.Request) -> httpx.Response:
        with app.state.session_factory() as other:
            agents.control_mission(other, mission.id, "cancel")
            other.commit()
        return httpx.Response(200, json=load_fixture("greenhouse_jobs.json"))

    respx.get(GH_URL).mock(side_effect=first_response)
    second = respx.get(LEVER_URL).mock(return_value=httpx.Response(200, json=[]))
    assert Worker(
        app.state.session_factory, fetcher_factory=lambda: make_fetcher(max_attempts=1)
    ).run_once()
    assert second.call_count == 0
