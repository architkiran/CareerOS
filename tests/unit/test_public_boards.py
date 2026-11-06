import pytest

from careeros.common.clock import utcnow
from careeros.modules.ingestion.service import run_source, upsert_job
from careeros.modules.sources.adapters.base import InvalidPayloadError
from careeros.modules.sources.adapters.public_boards import JobicyAdapter, RemotiveAdapter
from careeros.modules.sources.registry import SourceIn, add_source
from careeros.modules.sources.schemas import NormalizedJob


def test_public_boards_keep_real_employer_location_and_attribution():
    job = RemotiveAdapter().normalize(
        {
            "id": 1,
            "title": "Analyst",
            "company_name": "Manufacturing Co",
            "url": "https://remotive.com/remote-jobs/1",
            "description": "<p>SQL analytics</p>",
            "candidate_required_location": "USA",
            "publication_date": "2026-11-06T10:00:00",
            "job_type": "full_time",
        },
        "Remotive",
    )
    assert job.company_name == "Manufacturing Co" and job.workplace_type == "remote"
    assert job.source_url.startswith("https://remotive.com/") and job.salary_min is None
    job = JobicyAdapter().normalize(
        {
            "id": 2,
            "jobTitle": "BI Analyst",
            "companyName": "Consulting Co",
            "url": "https://jobicy.com/jobs/2",
            "jobGeo": "USA",
            "jobDescription": "SQL dashboards",
            "jobType": ["Full-Time"],
        },
        "Jobicy",
    )
    assert job.company_name == "Consulting Co" and job.employment_type == "full_time"


def test_jobicy_cursor_is_opaque_and_repeated_cursor_fails():
    class Feed:
        def get_json(self, *args, **kwargs):
            return {"jobs": [], "hasMore": True, "nextCursor": "repeat"}, 200

    with pytest.raises(InvalidPayloadError, match="pagination"):
        JobicyAdapter().fetch_raw(Feed(), "usa", 2)


@pytest.mark.parametrize("kind,token,gap", [("remotive", "public", 360), ("jobicy", "usa", 60)])
def test_feed_absence_does_not_close_jobs_and_provider_gap_applies_to_manual_runs(
    session, kind, token, gap
):  # type: ignore[no-untyped-def]
    source = add_source(session, SourceIn(type=kind, token=token, name=kind))
    job, _ = upsert_job(
        session,
        source,
        NormalizedJob(
            external_id="old",
            source_url="https://example.com/old",
            title="Old role",
            company_name="Employer",
            raw={"id": "old"},
        ),
        utcnow(),
    )
    session.commit()

    class Feed:
        calls = 0

        def get_json(self, *args, **kwargs):
            self.calls += 1
            return {"jobs": [], "hasMore": False, "nextCursor": None}, 200

    feed = Feed()
    assert run_source(session, source, feed).status == "success"
    assert run_source(session, source, feed).status == "skipped"
    assert feed.calls == 1
    session.refresh(job)
    assert job.status == "active"
    with pytest.raises(ValueError):
        SourceIn(type=kind, token="a-second-feed", name="bad")


def test_public_board_rejects_replaced_attribution_url():
    raw = {
        "id": 1,
        "title": "Analyst",
        "company_name": "Employer",
        "url": "https://evil.example/job",
    }
    with pytest.raises(InvalidPayloadError, match="original board URL"):
        RemotiveAdapter().normalize(raw, "Remotive")
