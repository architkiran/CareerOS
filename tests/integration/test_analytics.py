from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from careeros.common.clock import utcnow
from careeros.db.models import Application, Company, Job
from careeros.modules.analytics.service import compute
from careeros.modules.applications import service as apps
from careeros.modules.approvals import service as gate
from careeros.modules.jobs import service as jobs
from tests.integration.test_approvals import _ready_app


@pytest.fixture
def factory(app: FastAPI) -> sessionmaker[Session]:
    return app.state.session_factory  # type: ignore[no-any-return]


def _submit(f: sessionmaker[Session], data_dir: Path) -> str:
    app_id = _ready_app(f, data_dir)
    with f() as s:
        a = gate.request(s, gate.application_payload(s, app_id, False), data_dir)
        gate.decide(s, a.id, True, confirmed=True)
        gate.confirm_done(s, a.id, confirmed=True)
        s.commit()
    return app_id


def test_empty_analytics(factory: sessionmaker[Session], client: TestClient) -> None:
    with factory() as s:
        a = compute(s)
    assert [x.count for x in a.funnel] == [0] * 11
    assert a.by_lane == [] and a.recommendations == [] and a.median_days_to_submit is None
    html = client.get("/analytics").text
    assert 'data-testid="funnel"' in html and 'data-testid="recommendations-empty"' in html


def test_funnel_traces_events(factory: sessionmaker[Session], app: FastAPI) -> None:
    data_dir = Path(app.state.settings.data_dir)
    app_id = _submit(factory, data_dir)
    with factory() as s:
        app_row = s.get(Application, app_id)
        assert app_row is not None
        app_row.created_at = utcnow() - timedelta(days=3)
        app_row.submitted_at = utcnow() - timedelta(days=2)
        apps.set_status(s, app_id, "screen")
        apps.set_status(s, app_id, "rejected")
        c = Company(canonical_name="Other", normalized_name="other")
        s.add(c)
        s.flush()
        j = Job(
            canonical_url="https://o/1",
            company_id=c.id,
            title="X",
            normalized_title="x",
            description_hash="h",
            dedupe_key="k2",
        )
        s.add(j)
        s.flush()
        jobs.triage(s, j.id, "reject", "Needs 5+ years")
        s.commit()
        a = compute(s)
    f = {x.key: x.count for x in a.funnel}
    assert f["discovered"] == 2 and f["shortlisted"] == 1 and f["prepared"] == 1
    assert (f["approved"], f["submitted"], f["response"], f["screen"], f["interview"]) == (
        1,
        1,
        1,
        1,
        0,
    )
    step = next(x for x in a.funnel if x.key == "screen")
    assert step.from_previous is not None and step.from_previous.value == 1.0
    assert a.outcomes == {"rejected": 1}
    assert a.rejection_reasons == [("needs 5+ years", 1)]
    assert a.median_days_to_submit == pytest.approx(1.0, abs=0.1)
    assert a.median_days_to_response is not None and a.median_days_to_response >= 0
    [seg] = a.by_source
    assert seg.submitted == 1 and seg.response.hits == 1 and seg.response.small
    assert any("not enough data" in r for r in a.recommendations)


def test_analytics_page_renders_segments(
    factory: sessionmaker[Session], client: TestClient, app: FastAPI
) -> None:
    _submit(factory, Path(app.state.settings.data_dir))
    html = client.get("/analytics").text
    assert 'data-testid="by-week"' in html and "small sample" in html
    assert 'data-testid="recommendations"' in html
