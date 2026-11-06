from sqlalchemy import select

from careeros.db.models import AgentRun, Source
from careeros.modules.agents.service import start_source_mission
from careeros.modules.scheduler.worker import Worker
from careeros.modules.sources.intelligence import audit, proposals
from careeros.modules.sources.registry import SourceIn, add_source
from tests.conftest import post_form


def test_source_audit_is_durable_and_never_connects_automatically(app, session, client):  # type: ignore[no-untyped-def]
    m, created = start_source_mission(session)
    session.commit()
    other, again = start_source_mission(session)
    assert created and not again and other.id == m.id
    session.commit()
    assert Worker(app.state.session_factory).run_once()
    session.expire_all()
    run = session.scalars(select(AgentRun)).one()
    assert run.status == "succeeded" and run.result_json["metrics"]["candidate_feeds"] == 3
    assert session.scalars(select(Source)).all() == []
    assert "Recommended public feeds" in client.get("/sources").text
    assert post_form(client, "/sources/connect/wise").status_code == 303
    assert post_form(client, "/sources/connect/wise").status_code == 303
    assert len(session.scalars(select(Source)).all()) == 1
    assert len(proposals(session)) == 2
    assert client.post("/sources/audit").status_code == 403
    assert post_form(client, "/sources/connect/not-supported").status_code == 404


def test_disabled_feed_is_not_silently_reenabled(session):  # type: ignore[no-untyped-def]
    source = add_source(
        session, SourceIn(type="smartrecruiters", token="wise", name="Wise", enabled=False)
    )
    session.commit()
    report = audit(session)
    assert report["enabled_sources"] == 0 and len(proposals(session)) == 2
    assert source.enabled is False


def test_bounded_feed_failure_preserves_previously_seen_jobs(session):  # type: ignore[no-untyped-def]
    from careeros.common.clock import utcnow
    from careeros.modules.ingestion.service import run_source, upsert_job
    from careeros.modules.sources.schemas import NormalizedJob

    source = add_source(session, SourceIn(type="smartrecruiters", token="wise", name="Wise"))
    job, _ = upsert_job(
        session,
        source,
        NormalizedJob(
            external_id="1",
            source_url="https://jobs.smartrecruiters.com/wise/1",
            title="Analyst",
            company_name="Wise",
            raw={"id": "1"},
        ),
        utcnow(),
    )
    session.commit()

    class CappedFeed:
        def get_json(self, *args, **kwargs):
            return {"totalFound": 201, "content": []}, 200

    result = run_source(session, source, CappedFeed())
    assert result.status == "failed"
    session.refresh(job)
    assert job.status == "active" and job.closed_at is None
