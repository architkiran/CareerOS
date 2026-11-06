from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from careeros.db.models import (
    ActivityEvent,
    AgentRun,
    Application,
    Approval,
    Document,
    Mission,
    Task,
)
from careeros.modules.agents import service
from careeros.modules.applications import service as applications
from careeros.modules.documents import service as documents
from careeros.modules.scheduler.worker import Worker
from tests.conftest import post_form
from tests.integration.test_documents import _setup


@pytest.fixture
def factory(app: FastAPI) -> sessionmaker[Session]:
    return app.state.session_factory  # type: ignore[no-any-return]


def start(factory: sessionmaker[Session]) -> tuple[str, str]:
    job_id = _setup(factory)
    with factory() as session:
        app = applications.start_application(session, job_id)
        mission, created = service.start_application_mission(session, app.id)
        assert created
        session.commit()
        return app.id, mission.id


def test_prepares_private_verified_drafts_without_approval(
    factory: sessionmaker[Session], app: FastAPI, client: TestClient
) -> None:
    app_id, mission_id = start(factory)
    data_dir = Path(app.state.settings.data_dir)
    assert Worker(factory, data_dir=data_dir).run_once()
    with factory() as session:
        mission = session.get(Mission, mission_id)
        assert mission and mission.status == "degraded"  # format/review warnings stay visible
        run = service.runs_for(session, mission_id)[0]
        assert run.status == "succeeded"
        assert run.result_json["metrics"] == {"drafts": 2, "drafts_needing_review": 2}
        assert session.scalars(select(Approval)).all() == []
        candidate_app = session.get(Application, app_id)
        assert (
            candidate_app and candidate_app.status == "preparing" and not candidate_app.submitted_at
        )
        docs = session.scalars(select(Document)).all()
        assert len(docs) == 2
        for doc in docs:
            documents.verify_integrity(doc)
            assert doc.warnings_acknowledged_at is None
            assert "Rust" not in documents.load_content(doc).as_text()
            assert client.get(f"/documents/{doc.id}/download").status_code == 200
        assert "Test Person" not in str(run.result_json)
        assert "Test Person" not in str(session.scalars(select(ActivityEvent.message)).all())
    page = client.get(f"/missions/{mission_id}")
    assert "Application draft preparation" in page.text and "Open saved document" in page.text
    assert client.get("/agents/application").status_code == 200
    assert client.get(f"/applications/{app_id}").headers["cache-control"] == "no-store"
    assert "does not preserve the exact layout" in client.get(f"/applications/{app_id}").text


def test_duplicate_requests_and_reruns_reuse_drafts(
    factory: sessionmaker[Session], app: FastAPI
) -> None:
    app_id, mission_id = start(factory)
    with factory() as session:
        duplicate, created = service.start_application_mission(session, app_id)
        assert not created and duplicate.id == mission_id
        session.commit()
    worker = Worker(factory, data_dir=Path(app.state.settings.data_dir))
    assert worker.run_once()
    with factory() as session:
        fresh, created = service.start_application_mission(session, app_id)
        assert created and fresh.id != mission_id
        session.commit()
    assert worker.run_once()
    with factory() as session:
        assert len(session.scalars(select(Document)).all()) == 2
        assert len(session.scalars(select(AgentRun)).all()) == 2


def test_missing_and_completed_applications_rejected(factory: sessionmaker[Session]) -> None:
    with factory() as session, pytest.raises(LookupError):
        service.start_application_mission(session, "missing")
    app_id, _ = start(factory)
    with factory() as session:
        candidate_app = session.get(Application, app_id)
        assert candidate_app
        candidate_app.status = "submitted"
        session.commit()
    assert Worker(factory, data_dir=Path("unused")).run_once()
    with factory() as session:
        assert not session.scalars(select(Document)).all()
        run = session.scalars(select(AgentRun)).one()
        assert run.status == "retrying" and "no longer available" in (run.last_error or "")
        with pytest.raises(service.MissionConflict):
            service.start_application_mission(session, app_id)


def test_missing_data_directory_fails_without_writing(factory: sessionmaker[Session]) -> None:
    _, mission_id = start(factory)
    assert Worker(factory).run_once()
    with factory() as session:
        assert not session.scalars(select(Document)).all()
        assert service.runs_for(session, mission_id)[0].status == "retrying"


def test_mismatched_task_target_cannot_prepare_another_application(
    factory: sessionmaker[Session], app: FastAPI
) -> None:
    start(factory)
    with factory() as session:
        task = session.scalars(select(Task)).one()
        task.payload_json = {**task.payload_json, "application_id": "f" * 32}
        session.commit()
    assert Worker(factory, data_dir=Path(app.state.settings.data_dir)).run_once()
    with factory() as session:
        assert session.scalars(select(Document)).all() == []
        assert "target does not match" in (session.scalars(select(AgentRun)).one().last_error or "")


def test_prepare_route_is_csrf_protected_and_deduplicated(
    factory: sessionmaker[Session], client: TestClient
) -> None:
    app_id, mission_id = start(factory)
    assert client.post(f"/applications/{app_id}/prepare").status_code == 403
    response = post_form(client, f"/applications/{app_id}/prepare")
    assert response.status_code == 303 and response.headers["location"] == f"/missions/{mission_id}"
    assert post_form(client, "/applications/missing/prepare").status_code == 404


def test_on_demand_rollback_leaves_no_mission(factory: sessionmaker[Session]) -> None:
    job_id = _setup(factory)
    with factory() as session:
        app = applications.start_application(session, job_id)
        session.commit()
        service.start_application_mission(session, app.id)
        session.rollback()
        assert session.scalars(select(Mission)).all() == []
        assert session.scalars(select(Task)).all() == []
