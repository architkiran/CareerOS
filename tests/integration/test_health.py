from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from careeros.config import Settings
from careeros.main import create_app


def test_health_ok_when_migrated(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"]["ok"] is True
    assert body["database"]["journal_mode"] == "wal"
    assert body["database"]["foreign_keys"] is True
    assert body["schema"]["up_to_date"] is True
    assert body["localhost_only"] is True
    assert body["messages"] == []


@pytest.fixture
def unmigrated_client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as c:
        yield c
    app.state.engine.dispose()


def test_health_degraded_when_migrations_pending(unmigrated_client: TestClient) -> None:
    r = unmigrated_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["schema"]["up_to_date"] is False
    assert body["schema"]["current_revision"] is None
    assert any("careeros migrate" in m for m in body["messages"])


def test_health_error_when_database_unreachable(settings: Settings) -> None:
    app = create_app(settings)
    app.state.engine.dispose()
    # Point at a path whose parent directory does not exist, bypassing auto-create.
    app.state.engine = create_engine("sqlite:////nonexistent-careeros-dir/never/x.db")
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "error"
    assert body["database"]["ok"] is False
    assert body["database"]["error"] == "OperationalError"
    # Error detail must not leak filesystem paths.
    assert "nonexistent" not in r.text


def test_health_warns_when_not_localhost(migrated_settings: Settings) -> None:
    exposed = migrated_settings.model_copy(update={"app_host": "0.0.0.0"})  # noqa: S104
    app = create_app(exposed)
    with TestClient(app) as c:
        body = c.get("/health").json()
    assert body["localhost_only"] is False
    assert any("authentication" in m for m in body["messages"])
    app.state.engine.dispose()
