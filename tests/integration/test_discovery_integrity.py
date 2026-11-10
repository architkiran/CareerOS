from datetime import timedelta

import httpx
import pytest
import respx
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import JobRevision, JobSourceRecord, Source
from careeros.modules.ingestion.service import _close_unseen, run_source, upsert_job
from careeros.modules.sources.adapters.greenhouse import GreenhouseAdapter
from careeros.modules.sources.registry import SourceIn, add_source
from careeros.modules.sources.schemas import NormalizedJob
from careeros.modules.sources.text import safe_posting_url
from tests.helpers import GH_URL, make_fetcher


def payload(**changes: object) -> NormalizedJob:
    values = dict(
        external_id="1",
        source_url="https://example.test/careers?id=1#opening",
        title="Data Analyst",
        company_name="Example",
        description_text="SQL dashboards",
        raw={"id": "1"},
    )
    return NormalizedJob.model_validate(values | changes)


def source(session: Session, board: str = "examplepay") -> Source:
    return add_source(session, SourceIn(type="greenhouse", token=board, name="Example"))


def test_distinct_times_and_repeated_poll_stability(session: Session) -> None:
    now = utcnow()
    src = source(session)
    nj = payload(
        posted_at=now - timedelta(days=2),
        last_modified_at=now - timedelta(hours=1),
        publication_kind="original",
    )
    job, _ = upsert_job(session, src, nj, now)
    seen = job.first_seen_at
    later = now + timedelta(minutes=30)
    same, outcome = upsert_job(session, src, nj, later)
    assert same.id == job.id and outcome == "unchanged"
    assert job.first_seen_at == seen and job.fetched_at == later and job.last_seen_at == later
    assert job.published_at == nj.posted_at and job.last_modified_at == nj.last_modified_at
    rec = session.scalar(select(JobSourceRecord))
    assert rec.fetched_at == later and rec.published_at == nj.posted_at and rec.is_listed
    assert list(session.scalars(select(JobRevision))) == []


def test_only_modified_date_never_becomes_publication(session: Session) -> None:
    now = utcnow()
    raw = {
        "id": 1,
        "title": "Analyst",
        "absolute_url": "https://example.test/job/1",
        "updated_at": now.isoformat(),
    }
    normalized = GreenhouseAdapter().normalize(raw, "Example")
    assert normalized.posted_at is None and normalized.last_modified_at == now
    job, _ = upsert_job(session, source(session), normalized, now)
    assert job.published_at is None


def test_material_update_keeps_history_and_first_seen(session: Session) -> None:
    now = utcnow()
    src = source(session)
    job, _ = upsert_job(session, src, payload(), now)
    changed = payload(description_text="SQL, Python and reporting", raw={"id": "1", "v": 2})
    same, outcome = upsert_job(session, src, changed, now + timedelta(hours=1))
    session.flush()
    revision = session.scalar(select(JobRevision))
    assert outcome == "updated" and same.id == job.id and job.first_seen_at == now
    assert revision.previous_json["description_text"] == "SQL dashboards"
    assert revision.current_json["description_text"] == changed.description_text
    assert job.material_updated_at == now + timedelta(hours=1)


def test_url_changes_retain_exact_destinations(session: Session) -> None:
    now = utcnow()
    src = source(session)
    original = payload()
    job, _ = upsert_job(session, src, original, now)
    changed = payload(
        source_url="https://employer.test/jobs?position=1#details", raw={"id": "1", "v": 2}
    )
    same, _ = upsert_job(session, src, changed, now + timedelta(minutes=1))
    session.flush()
    revision = session.scalar(select(JobRevision))
    assert same.id == job.id
    assert revision.previous_json["source_url"] == original.source_url
    assert revision.current_json["source_url"] == changed.source_url
    assert job.canonical_url == changed.source_url


def test_repost_candidates_preserve_both_ids_and_history(session: Session) -> None:
    src = source(session)
    now = utcnow()
    original, _ = upsert_job(session, src, payload(), now)
    repost, outcome = upsert_job(session, src, payload(external_id="2", raw={"id": "2"}), now)
    session.flush()
    assert outcome == "possible_duplicate" and repost.possible_duplicate_of_id == original.id
    assert {r.external_id for r in session.scalars(select(JobSourceRecord))} == {"1", "2"}
    assert session.scalar(select(JobRevision)).change_type == "possible_repost"


def test_multisource_presence_needs_all_successful_absences(session: Session) -> None:
    now = utcnow()
    first, second = source(session), source(session, "other")
    job, _ = upsert_job(session, first, payload(), now)
    other, _ = upsert_job(session, second, payload(external_id="x"), now)
    assert other.id == job.id
    assert _close_unseen(session, first, set(), now) == 0 and job.status == "active"
    assert _close_unseen(session, second, set(), now + timedelta(minutes=1)) == 1
    assert job.status == "closed"
    upsert_job(session, first, payload(), now + timedelta(minutes=2))
    session.flush()
    assert job.status == "active"
    assert {r.change_type for r in session.scalars(select(JobRevision))} == {"closed", "reopened"}


@respx.mock
def test_partial_refresh_does_not_close_missing_jobs(session: Session) -> None:
    src = source(session)
    job, _ = upsert_job(session, src, payload(), utcnow())
    session.commit()
    respx.get(GH_URL).mock(return_value=httpx.Response(200, json={"jobs": [{"id": "broken"}]}))
    result = run_source(session, src, make_fetcher(max_attempts=1))
    assert result.status == "partial" and result.closed == 0
    assert job.status == "active"


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "javascript:alert(1)",
        "https:///nohost",
        "https://user:pass@example.test/job",
        "https://example.test:bad/x",
        "https://example.test/\\evil",
        "https://example.test/white space",
    ],
)
def test_invalid_urls_are_not_usable_destinations(url: str | None) -> None:
    assert safe_posting_url(url) is None
    with pytest.raises(ValidationError):
        payload(source_url=url)
