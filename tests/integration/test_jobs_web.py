import json
from datetime import timedelta

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from careeros.common.clock import utcnow
from careeros.db.models import ActivityEvent, Company, Job, PipelineRun, Task
from careeros.modules.events.service import record_event
from careeros.modules.ingestion.service import run_all
from careeros.modules.scheduler import queue
from careeros.modules.sources import registry
from careeros.web.routes import events as events_route
from tests.conftest import post_form
from tests.helpers import ASHBY_URL, GH_URL, LEVER_URL, load_fixture, make_fetcher


@pytest.fixture
def seeded(app: FastAPI) -> FastAPI:
    """Ingest the three fixture boards through the real pipeline."""
    with app.state.session_factory() as s:
        for t, tok, name in [
            ("greenhouse", "examplepay", "ExamplePay"),
            ("lever", "examplebank", "ExampleBank"),
            ("ashby", "examplecard", "ExampleCard"),
        ]:
            registry.add_source(s, registry.SourceIn(type=t, token=tok, name=name))  # type: ignore[arg-type]
        s.commit()
    with respx.mock:
        respx.get(GH_URL).mock(
            return_value=httpx.Response(200, json=load_fixture("greenhouse_jobs.json"))
        )
        respx.get(LEVER_URL).mock(
            return_value=httpx.Response(200, json=load_fixture("lever_postings.json"))
        )
        respx.get(ASHBY_URL).mock(
            return_value=httpx.Response(200, json=load_fixture("ashby_jobs.json"))
        )
        run_all(app.state.session_factory, make_fetcher(max_attempts=1))
    return app


def _job(app: FastAPI, title: str) -> Job:
    with app.state.session_factory() as s:
        return s.scalars(select(Job).where(Job.title == title)).one()


# ---------- inbox ----------


def test_inbox_empty_state(client: TestClient) -> None:
    r = client.get("/jobs")
    assert r.status_code == 200 and 'data-testid="jobs-empty"' in r.text


def test_inbox_lists_jobs(seeded: FastAPI, client: TestClient) -> None:
    html = client.get("/jobs").text
    assert html.count('data-testid="job-row"') == 7
    assert "Product Analyst" in html and "ExampleCard" in html
    assert "not stated" in html  # Greenhouse employment type stays unknown


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("q=analyst", 4),
        ("q=EXAMPLEBANK", 2),
        ("q=pipelines", 1),
        ("workplace=remote", 3),
        ("workplace=hybrid", 1),
        ("days=1", 7),
        ("q=nothing-matches", 0),
    ],
)
def test_inbox_filters(seeded: FastAPI, client: TestClient, query: str, expected: int) -> None:
    html = client.get(f"/jobs?{query}").text
    assert html.count('data-testid="job-row"') == expected
    if expected == 0:
        assert 'data-testid="jobs-no-match"' in html


def test_inbox_source_filter(seeded: FastAPI, client: TestClient) -> None:
    with seeded.state.session_factory() as s:
        lever = next(x for x in registry.list_sources(s) if x.source_type == "lever")
    assert client.get(f"/jobs?source_id={lever.id}").text.count('data-testid="job-row"') == 2


def test_invalid_filter_values_are_ignored(seeded: FastAPI, client: TestClient) -> None:
    r = client.get("/jobs?triage=bogus&status=weird&workplace=moon")
    assert r.status_code == 200 and r.text.count('data-testid="job-row"') == 7
    assert client.get("/jobs?days=0").status_code == 422
    assert client.get("/jobs?page=0").status_code == 422


def test_search_is_escaped(seeded: FastAPI, client: TestClient) -> None:
    html = client.get("/jobs?q=<script>x</script>").text
    assert "<script>x</script>" not in html


def test_closed_jobs_filter(seeded: FastAPI, client: TestClient) -> None:
    with seeded.state.session_factory() as s:
        job = s.scalars(select(Job).where(Job.title == "Product Analyst")).one()
        job.status = "closed"
        s.commit()
    assert client.get("/jobs").text.count('data-testid="job-row"') == 6
    assert client.get("/jobs?status=closed").text.count('data-testid="job-row"') == 1
    assert client.get("/jobs?status=all").text.count('data-testid="job-row"') == 7


def test_pagination(app: FastAPI, client: TestClient) -> None:
    with app.state.session_factory() as s:
        c = Company(canonical_name="Big", normalized_name="big")
        s.add(c)
        s.flush()
        for i in range(55):
            s.add(
                Job(
                    canonical_url=f"https://x.test/{i}",
                    company_id=c.id,
                    title=f"Role {i:02d}",
                    normalized_title=f"role {i}",
                    description_hash="h",
                    dedupe_key=f"k{i}",
                    first_seen_at=utcnow() - timedelta(minutes=i),
                )
            )
        s.commit()
    first = client.get("/jobs").text
    assert first.count('data-testid="job-row"') == 50 and "Page 1 of 2" in first
    second = client.get("/jobs?page=2").text
    assert second.count('data-testid="job-row"') == 5 and "Role 54" in second


# ---------- detail and triage ----------


def test_job_detail(seeded: FastAPI, client: TestClient) -> None:
    job = _job(seeded, "Data Analyst")
    html = client.get(f"/jobs/{job.id}").text
    assert 'data-testid="sightings"' in html and "ExamplePay (greenhouse)" in html
    assert 'rel="noopener noreferrer nofollow"' in html
    assert "<script>" not in html.split("Description")[-1]
    assert "Ignore previous instructions" in html  # shown as inert text, never acted on
    assert "not disclosed" in html and "unknown" in html


def test_job_detail_salary(seeded: FastAPI, client: TestClient) -> None:
    html = client.get(f"/jobs/{_job(seeded, 'Product Analyst').id}").text
    assert "110,000" in html and "140,000" in html


def test_job_detail_404(client: TestClient) -> None:
    assert client.get("/jobs/missing").status_code == 404


@pytest.mark.parametrize(
    ("action", "status"),
    [("shortlist", "shortlisted"), ("save", "saved"), ("reviewed", "reviewed")],
)
def test_triage_actions(seeded: FastAPI, client: TestClient, action: str, status: str) -> None:
    job = _job(seeded, "Data Analyst")
    r = post_form(client, f"/jobs/{job.id}/triage", {"action": action})
    assert r.status_code == 303
    assert _job(seeded, "Data Analyst").triage_status == status
    assert client.get(f"/jobs?triage={status}").text.count('data-testid="job-row"') == 1


def test_reject_requires_reason_and_hides_job(seeded: FastAPI, client: TestClient) -> None:
    job = _job(seeded, "Data Analyst")
    r = post_form(client, f"/jobs/{job.id}/triage", {"action": "reject", "reason": "  "})
    assert r.status_code == 422 and "Give a reason" in r.text
    assert _job(seeded, "Data Analyst").triage_status == "new"
    post_form(client, f"/jobs/{job.id}/triage", {"action": "reject", "reason": "Needs 5+ years"})
    rejected = _job(seeded, "Data Analyst")
    assert rejected.triage_status == "rejected" and rejected.triage_reason == "Needs 5+ years"
    assert client.get("/jobs").text.count('data-testid="job-row"') == 6
    assert client.get("/jobs?triage=rejected").text.count('data-testid="job-row"') == 1
    post_form(client, f"/jobs/{job.id}/triage", {"action": "reset"})
    reset = _job(seeded, "Data Analyst")
    assert reset.triage_status == "new" and reset.triage_reason is None and reset.triaged_at is None


def test_triage_unknown_action_and_missing_job(seeded: FastAPI, client: TestClient) -> None:
    job = _job(seeded, "Data Analyst")
    assert post_form(client, f"/jobs/{job.id}/triage", {"action": "apply"}).status_code == 422
    assert post_form(client, "/jobs/missing/triage", {"action": "save"}).status_code == 404


def test_triage_requires_csrf(seeded: FastAPI, client: TestClient) -> None:
    job = _job(seeded, "Data Analyst")
    assert client.post(f"/jobs/{job.id}/triage", data={"action": "save"}).status_code == 403


def test_triage_recorded_in_activity(seeded: FastAPI, client: TestClient) -> None:
    job = _job(seeded, "Data Analyst")
    post_form(client, f"/jobs/{job.id}/triage", {"action": "shortlist"})
    assert "job.triaged" in client.get("/").text


def test_possible_duplicate_group_shown(app: FastAPI, client: TestClient) -> None:
    with app.state.session_factory() as s:
        c = Company(canonical_name="Dup Co", normalized_name="dup co")
        s.add(c)
        s.flush()
        a = Job(
            canonical_url="https://x.test/a",
            company_id=c.id,
            title="Analyst",
            normalized_title="analyst",
            description_hash="1",
            dedupe_key="same",
        )
        s.add(a)
        s.flush()
        s.add(
            Job(
                canonical_url="https://x.test/b",
                company_id=c.id,
                title="Analyst",
                normalized_title="analyst",
                description_hash="2",
                dedupe_key="same",
                possible_duplicate_of_id=a.id,
            )
        )
        s.commit()
        a_id = a.id
    assert client.get("/jobs?dupes=true").text.count('data-testid="job-row"') == 1
    assert 'data-testid="duplicate-group"' in client.get(f"/jobs/{a_id}").text


# ---------- run controls and overview ----------


def test_run_discovery_button_queues_once(app: FastAPI, client: TestClient) -> None:
    r = post_form(client, "/pipeline/run")
    assert r.headers["location"] == "/?queued=1"
    assert post_form(client, "/pipeline/run").headers["location"] == "/?queued=already"
    with app.state.session_factory() as s:
        assert len(s.scalars(select(Task)).all()) == 1
    assert "already queued" in client.get("/?queued=already").text


def test_run_source_now(seeded: FastAPI, client: TestClient) -> None:
    with seeded.state.session_factory() as s:
        sid = registry.list_sources(s)[0].id
    assert post_form(client, f"/sources/{sid}/run").headers["location"] == "/sources?queued=1"
    assert post_form(client, f"/sources/{sid}/run").headers["location"] == "/sources?queued=already"
    assert post_form(client, "/sources/missing/run").status_code == 404
    assert "Fetch queued" in client.get("/sources?queued=1").text


def test_retry_dead_task_from_dashboard(app: FastAPI, client: TestClient) -> None:
    with app.state.session_factory() as s:
        queue.enqueue(s, "ingest.all", max_attempts=1)
        s.commit()
        task = queue.claim(s, "w")
        assert task is not None
        queue.fail(s, task, "simulated failure")
        s.commit()
        tid = task.id
    html = client.get("/").text
    assert "simulated failure" in html and 'data-testid="dead-count">1 failed' in html
    assert post_form(client, f"/tasks/{tid}/retry").status_code == 303
    assert post_form(client, f"/tasks/{tid}/retry").status_code == 404


def test_overview_stats(seeded: FastAPI, client: TestClient) -> None:
    job = _job(seeded, "Product Analyst")
    post_form(client, f"/jobs/{job.id}/triage", {"action": "shortlist"})
    html = client.get("/partials/overview").text
    assert 'data-testid="stat-new-today">7<' in html
    assert 'data-testid="stat-shortlisted">1<' in html
    assert "3 of 3 enabled" in html


def test_overview_shows_overdue_schedule(app: FastAPI, client: TestClient) -> None:
    app.state.settings = app.state.settings.model_copy(update={"scheduler_enabled": True})
    with app.state.session_factory() as s:
        s.add(
            PipelineRun(
                pipeline_name="discovery",
                status="success",
                started_at=utcnow() - timedelta(days=3),
                finished_at=utcnow() - timedelta(days=3),
            )
        )
        s.commit()
    assert 'data-testid="schedule-overdue"' in client.get("/").text


def test_dashboard_has_live_hooks(client: TestClient) -> None:
    html = client.get("/").text
    assert "data-live-feed" in html and "data-live-stats" in html and "/static/app.js" in html


def test_app_js_never_injects_event_text_as_html(client: TestClient) -> None:
    js = client.get("/static/app.js").text
    assert "textContent" in js
    assert js.count("innerHTML") == 1  # only for the server-rendered, escaped stats partial


# ---------- SSE and polling ----------


def _add_event(app: FastAPI, message: str, meta: dict | None = None) -> int:  # type: ignore[type-arg]
    with app.state.session_factory() as s:
        e = record_event(s, "test.event", message, metadata=meta or {})
        s.commit()
        return e.id


def _read_stream(client: TestClient, url: str, headers: dict[str, str] | None = None) -> str:
    with client.stream("GET", url, headers=headers or {}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        return "".join(r.iter_text())


@pytest.fixture
def short_stream(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    app.state.sse_max_seconds = 0.3
    monkeypatch.setattr(events_route, "POLL_INTERVAL_SECONDS", 0.05)
    return app


def test_sse_streams_events_after_cursor(short_stream: FastAPI, client: TestClient) -> None:
    first = _add_event(short_stream, "first")
    _add_event(short_stream, "second", {"secret": "do-not-stream"})
    body = _read_stream(client, f"/events/stream?after={first}")
    assert body.startswith("retry: 3000")
    assert "second" in body and '"message": "first"' not in body
    assert "event: activity" in body and "do-not-stream" not in body
    frames = [f for f in body.split("\n\n") if f.startswith("id: ")]
    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert set(payload) == {
        "id",
        "event_type",
        "message",
        "entity_type",
        "entity_id",
        "created_at",
        "created_local",
    }


def test_sse_last_event_id_header_wins(short_stream: FastAPI, client: TestClient) -> None:
    a = _add_event(short_stream, "alpha")
    _add_event(short_stream, "beta")
    body = _read_stream(client, "/events/stream?after=0", {"Last-Event-ID": str(a)})
    assert "beta" in body and "alpha" not in body


def test_sse_without_cursor_starts_from_now(short_stream: FastAPI, client: TestClient) -> None:
    _add_event(short_stream, "old news")
    assert "old news" not in _read_stream(client, "/events/stream")


def test_sse_heartbeat(short_stream: FastAPI, client: TestClient) -> None:
    short_stream.state.settings = short_stream.state.settings.model_copy(
        update={"sse_heartbeat_seconds": 1}
    )
    short_stream.state.sse_max_seconds = 1.2
    assert ": heartbeat" in _read_stream(client, "/events/stream")


def test_sse_rejects_negative_cursor(client: TestClient) -> None:
    assert client.get("/events/stream?after=-1").status_code == 422


def test_polling_feed(app: FastAPI, client: TestClient) -> None:
    a = _add_event(app, "one")
    _add_event(app, "two")
    data = client.get(f"/events/feed?after={a}").json()
    assert [e["message"] for e in data["events"]] == ["two"]
    assert client.get("/events/feed?after=999999").json() == {"events": []}
    with app.state.session_factory() as s:
        assert s.scalars(select(ActivityEvent)).all()  # sanity
