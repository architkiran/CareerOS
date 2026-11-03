from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from careeros.config import Settings
from careeros.db.models import ActivityEvent
from careeros.main import create_app


def test_dashboard_renders_ok_with_empty_activity(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert 'data-testid="overall-status">ok<' in r.text
    assert 'data-testid="activity-empty"' in r.text
    assert "Up to date" in r.text
    assert "$0.00/day" in r.text


def test_dashboard_shows_events_escaped_in_local_time(app: FastAPI, client: TestClient) -> None:
    with app.state.session_factory() as session:
        session.add(ActivityEvent(event_type="system.test", message="<script>alert(1)</script>"))
        session.commit()
    r = client.get("/")
    assert "system.test" in r.text
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text
    assert ("EST" in r.text) or ("EDT" in r.text)


@pytest.fixture
def unmigrated_client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as c:
        yield c
    app.state.engine.dispose()


def test_dashboard_degraded_state(unmigrated_client: TestClient) -> None:
    r = unmigrated_client.get("/")
    assert r.status_code == 200
    assert 'data-testid="overall-status">degraded<' in r.text
    assert "careeros migrate" in r.text
    assert "Migrations pending" in r.text


def test_security_headers(client: TestClient) -> None:
    r = client.get("/")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_static_css_served(client: TestClient) -> None:
    r = client.get("/static/app.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]


def test_api_docs_disabled(client: TestClient) -> None:
    assert client.get("/docs").status_code == 404
