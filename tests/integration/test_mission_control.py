import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from careeros.config import Settings
from careeros.db.models import AgentRun, Mission, Task
from careeros.main import create_app
from careeros.modules.agents import service
from careeros.modules.agents.registry import AGENTS
from careeros.modules.scheduler.worker import Worker
from tests.conftest import post_form


def test_control_empty_state_and_permissions(client: TestClient) -> None:
    response = client.get("/mission-control")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "Your next opportunity starts here" in response.text
    assert "No missions yet" in response.text
    assert "Not observed recently" in response.text
    assert client.post("/missions").status_code == 403
    assert "Planned work; these are not running agents." in client.get("/agents").text
    assert "cannot submit applications" in client.get("/agents/discovery").text
    assert client.get("/agents/missing").status_code == 404
    assert client.get("/missions/missing").status_code == 404
    assert post_form(client, "/missions/missing/pause").status_code == 404


def test_start_controls_history_and_live_partial(app: FastAPI, client: TestClient) -> None:
    response = post_form(client, "/missions")
    assert response.status_code == 303
    path = response.headers["location"]
    assert post_form(client, "/missions").headers["location"] == path
    detail = client.get(path)
    assert "One mission. Every step visible." in detail.text
    assert "After <a href=" in detail.text
    assert post_form(client, path + "/resume").status_code == 409
    assert post_form(client, path + "/pause").status_code == 303
    assert not Worker(app.state.session_factory).run_once()
    assert "paused" in client.get(path).text
    assert post_form(client, path + "/resume").status_code == 303
    for _ in range(len(AGENTS)):
        assert Worker(app.state.session_factory).run_once()
    html = client.get(path).text
    assert "Attempt 1" in html and "degraded" in html
    assert "No enabled sources." in html
    partial = client.get("/partials/mission-control")
    assert "6 of 6 steps complete" in partial.text
    assert "Recent" in partial.text
    assert "Updated the career funnel" in client.get("/agents/analytics").text
    assert post_form(client, path + "/cancel").status_code == 409


def test_legacy_retry_routes_through_mission_gate(app: FastAPI, client: TestClient) -> None:
    with app.state.session_factory() as session:
        mission, _ = service.start_mission(session)
        run = service.runs_for(session, mission.id)[0]
        task = session.get(Task, run.task_id)
        assert task
        mission.status, run.status, task.status = "failed", "failed", "dead"
        task_id, run_id = task.id, run.id
        session.commit()
    assert post_form(client, f"/tasks/{task_id}/retry").status_code == 303
    with app.state.session_factory() as session:
        assert session.get(AgentRun, run_id).status == "queued"
        assert session.scalars(select(Mission)).one().status == "running"
    assert post_form(client, f"/agent-runs/{run_id}/retry").status_code == 409


def test_dashboard_escapes_persisted_summaries(app: FastAPI, client: TestClient) -> None:
    with app.state.session_factory() as session:
        mission, _ = service.start_mission(session)
        run = service.runs_for(session, mission.id)[0]
        run.summary = "<script>malicious()</script>"
        session.commit()
    response = client.get("/mission-control")
    assert "<script>malicious()" not in response.text
    assert "&lt;script&gt;malicious()" in response.text


def test_pending_migration_has_honest_empty_state(settings: Settings) -> None:
    app = create_app(settings)
    try:
        with TestClient(app) as client:
            assert "careeros migrate" in client.get("/mission-control").text
            assert "careeros migrate" in client.get("/partials/mission-control").text
            assert post_form(client, "/missions").status_code == 409
    finally:
        app.state.engine.dispose()


@pytest.mark.parametrize("path", ["/missions", "/missions/x/pause", "/agent-runs/x/retry"])
def test_every_mission_mutation_requires_csrf(client: TestClient, path: str) -> None:
    assert client.post(path).status_code == 403


def test_five_workspace_navigation_and_on_demand_activity(client, app):  # type: ignore[no-untyped-def]
    from careeros.modules.agents.service import start_application_mission
    from careeros.modules.applications.service import start_application
    from tests.integration.test_documents import _setup

    factory = app.state.session_factory
    job_id = _setup(factory)
    with factory() as session:
        application = start_application(session, job_id)
        mission, _ = start_application_mission(session, application.id)
        session.commit()
    response = client.get("/mission-control")
    assert response.status_code == 200
    html = response.text
    main_nav = html.split('data-testid="workspace-nav"')[1].split("</nav>")[0]
    assert main_nav.count("<a ") == 5
    assert "Career library" in main_nav and "Resume references" not in main_nav
    assert "What your team is doing" in html and "1 active tasks" in html
    assert f"/missions/{mission.id}" in html and "Application drafts" in html
    assert "Past work and mission history" in html
    for path in ["/jobs", "/applications", "/profile", "/sources", "/companies", "/interviews"]:
        assert 'aria-label="Workspace sections"' in client.get(path).text
