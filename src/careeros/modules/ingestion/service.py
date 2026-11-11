"""Normalize → dedupe → persist, plus per-source run bookkeeping.

Dedupe precedence (docs/PIPELINE.md):
1. same source + external id
2. canonical URL
3. same company + normalized title + location and same description hash
4. same company + title + location but different description: kept as a new job
   flagged `possible_duplicate_of_id` for review
Source provenance is never discarded: every source sighting keeps its record.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from careeros.common.clock import utcnow
from careeros.db.models import Company, Job, JobRevision, JobSourceRecord, Source, SourceRun
from careeros.db.models.jobs import AGGREGATOR_TYPES, PARTIAL_SNAPSHOT_TYPES
from careeros.modules.events.service import record_event
from careeros.modules.sources.adapters import ADAPTERS, InvalidPayloadError
from careeros.modules.sources.http import (
    Fetcher,
    FetchError,
    SourceBlockedError,
    SourceNotFoundError,
)
from careeros.modules.sources.schemas import NormalizedJob
from careeros.modules.sources.text import (
    canonicalize_url,
    normalize_company,
    normalize_key,
    normalize_space,
    sha256,
)

logger = logging.getLogger(__name__)

BLOCKED_DISABLE_THRESHOLD = 3
Outcome = Literal["new", "updated", "unchanged", "duplicate", "possible_duplicate"]


def get_or_create_company(session: Session, name: str) -> Company:
    key = normalize_company(name) or normalize_key(name)
    company = session.scalars(select(Company).where(Company.normalized_name == key)).first()
    if company is None:
        company = Company(canonical_name=normalize_space(name), normalized_name=key)
        session.add(company)
        session.flush()
    return company


def dedupe_key(company_id: str, title: str, location: str | None) -> str:
    return sha256(f"{company_id}|{normalize_key(title)}|{normalize_key(location)}")


# Bump when an adapter extracts more from the same raw payload, so stored jobs are re-normalised
# on the next run (they count as "updated") instead of keeping stale parsed fields.
NORMALIZER_VERSION = "3"


def _raw_hash(raw: dict[str, Any]) -> str:
    return sha256(NORMALIZER_VERSION + json.dumps(raw, sort_keys=True, default=str))


def _apply(job: Job, nj: NormalizedJob, company_id: str) -> None:
    desc = nj.description_text
    job.company_id = company_id
    job.title = nj.title
    job.normalized_title = normalize_key(nj.title)
    job.location_text = nj.location_text
    job.workplace_type = nj.workplace_type
    job.employment_type = nj.employment_type
    job.department = nj.department
    job.description_text = desc
    job.description_hash = sha256(normalize_space(desc).lower())
    job.dedupe_key = dedupe_key(company_id, nj.title, nj.location_text)
    job.salary_min = nj.salary_min
    job.salary_max = nj.salary_max
    job.salary_currency = nj.salary_currency
    job.salary_interval = nj.salary_interval
    job.posted_at = nj.posted_at
    job.publication_kind = nj.publication_kind
    job.last_modified_at = nj.last_modified_at


def _snapshot(job: Job) -> dict[str, Any]:
    return {
        key: getattr(job, key)
        for key in (
            "title",
            "company_id",
            "location_text",
            "workplace_type",
            "employment_type",
            "description_text",
            "salary_min",
            "salary_max",
            "salary_currency",
            "salary_interval",
            "canonical_url",
            "status",
        )
    }


def _revision(
    session: Session,
    job: Job,
    source: Source,
    now: datetime,
    kind: str,
    before: dict[str, Any],
    source_urls: tuple[str, str] | None = None,
) -> None:
    previous, current = dict(before), _snapshot(job)
    if source_urls:
        previous["source_url"], current["source_url"] = source_urls
    session.add(
        JobRevision(
            job_id=job.id,
            source_id=source.id,
            observed_at=now,
            change_type=kind,
            previous_json=previous,
            current_json=current,
        )
    )


def _source_times(record: JobSourceRecord, nj: NormalizedJob, now: datetime) -> None:
    record.published_at = nj.posted_at
    record.publication_kind = nj.publication_kind
    record.last_modified_at = nj.last_modified_at
    record.fetched_at = now
    record.is_listed = True


def _reopen(job: Job) -> None:
    if job.status == "closed":
        job.status = "active"
        job.closed_at = None


def upsert_job(
    session: Session, source: Source, nj: NormalizedJob, now: datetime
) -> tuple[Job, Outcome]:
    company = get_or_create_company(session, nj.company_name)
    raw_hash = _raw_hash(nj.raw)

    # 1. same source + external id
    record = session.scalars(
        select(JobSourceRecord).where(
            JobSourceRecord.source_id == source.id, JobSourceRecord.external_id == nj.external_id
        )
    ).first()
    if record is not None:
        job = session.get(Job, record.job_id)
        assert job is not None
        before = _snapshot(job)
        previous_url = record.source_url
        record.last_seen_at = now
        job.last_seen_at = now
        job.fetched_at = now
        _source_times(record, nj, now)
        was_closed = job.status == "closed"
        _reopen(job)
        if record.raw_hash == raw_hash:
            if was_closed:
                _revision(session, job, source, now, "reopened", before)
            return job, "unchanged"
        record.raw_json = nj.raw
        record.raw_hash = raw_hash
        record.source_url = nj.source_url
        _apply(job, nj, company.id)
        # A stable provider ID may move to another exact employer posting URL.
        if source.source_type not in AGGREGATOR_TYPES:
            job.canonical_url = canonicalize_url(nj.source_url)
        if before != _snapshot(job):
            job.sponsorship_checked_at = None
            job.material_updated_at = now
            _revision(
                session,
                job,
                source,
                now,
                "reopened" if was_closed else "updated",
                before,
                (previous_url, nj.source_url),
            )
            return job, "updated"
        if previous_url != nj.source_url:
            _revision(
                session,
                job,
                source,
                now,
                "source_url_changed",
                before,
                (previous_url, nj.source_url),
            )
        return job, "unchanged"

    canonical = canonicalize_url(nj.source_url)
    desc_hash = sha256(normalize_space(nj.description_text).lower())
    key = dedupe_key(company.id, nj.title, nj.location_text)

    # 2. canonical URL, 3. company + title + location + same description.
    # A job already listed by *this* source under another id is a different posting
    # on the same board, never a cross-source duplicate.
    def other_source_only(candidate: Job) -> bool:
        return not session.scalars(
            select(JobSourceRecord.id).where(
                JobSourceRecord.job_id == candidate.id, JobSourceRecord.source_id == source.id
            )
        ).first()

    url_hits = list(session.scalars(select(Job).where(Job.canonical_url == canonical)))
    match = next((c for c in url_hits if other_source_only(c)), None)
    possible: Job | None = None
    if match is None:
        candidates = list(session.scalars(select(Job).where(Job.dedupe_key == key)))
        same_desc = [c for c in candidates if c.description_hash == desc_hash]
        match = next((c for c in same_desc if other_source_only(c)), None)
        if match is None and (candidates or url_hits):
            possible = (candidates or url_hits)[0]

    outcome: Outcome
    if match is not None:
        match.last_seen_at = now
        match.fetched_at = now
        _reopen(match)
        if not match.description_text and nj.description_text:
            # A third-party stub had no posting text; the fuller sighting supplies it.
            before = _snapshot(match)
            _apply(match, nj, company.id)
            if source.source_type not in AGGREGATOR_TYPES:
                match.canonical_url = canonical
            match.material_updated_at = now
            _revision(session, match, source, now, "updated", before)
        job, outcome = match, "duplicate"
    else:
        job = Job(canonical_url=canonical, first_seen_at=now, last_seen_at=now, fetched_at=now)
        _apply(job, nj, company.id)
        if possible is not None:
            job.possible_duplicate_of_id = possible.id
        session.add(job)
        session.flush()
        outcome = "possible_duplicate" if possible is not None else "new"

    session.add(
        JobSourceRecord(
            job_id=job.id,
            source_id=source.id,
            external_id=nj.external_id,
            source_url=nj.source_url,
            raw_json=nj.raw,
            raw_hash=raw_hash,
            published_at=nj.posted_at,
            publication_kind=nj.publication_kind,
            last_modified_at=nj.last_modified_at,
            fetched_at=now,
            is_listed=True,
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    if possible is not None:
        _revision(session, job, source, now, "possible_repost", _snapshot(possible))
    session.flush()
    return job, outcome


def _touch_seen(session: Session, source: Source, external_id: str, now: datetime) -> None:
    record = session.scalars(
        select(JobSourceRecord).where(
            JobSourceRecord.source_id == source.id, JobSourceRecord.external_id == external_id
        )
    ).first()
    if record is None:
        return
    record.last_seen_at = now
    record.is_listed = True
    job = session.get(Job, record.job_id)
    if job is not None:
        job.last_seen_at = now
        _reopen(job)


def _close_unseen(session: Session, source: Source, seen_ids: set[str], now: datetime) -> int:
    """Close jobs this source no longer lists, unless another source still lists them."""
    closed = 0
    records = session.scalars(select(JobSourceRecord).where(JobSourceRecord.source_id == source.id))
    for rec in records:
        if rec.external_id in seen_ids:
            continue
        rec.is_listed = False
        job = session.get(Job, rec.job_id)
        if job is None or job.status != "active":
            continue
        others = session.scalars(
            select(JobSourceRecord)
            .join(Source, Source.id == JobSourceRecord.source_id)
            .where(
                JobSourceRecord.job_id == job.id,
                JobSourceRecord.source_id != source.id,
                Source.source_type.not_in(AGGREGATOR_TYPES),
            )
        ).all()
        if any(o.is_listed is not False for o in others):
            continue
        before = _snapshot(job)
        job.status = "closed"
        job.closed_at = now
        _revision(session, job, source, now, "closed", before)
        closed += 1
    return closed


@dataclass
class RunSummary:
    source_id: str
    source_name: str
    status: str
    fetched: int = 0
    new: int = 0
    updated: int = 0
    duplicates: int = 0
    invalid: int = 0
    closed: int = 0
    error: str | None = None


def _fail(session: Session, source: Source, run: SourceRun, exc: FetchError, now: datetime) -> None:
    run.status = "failed"
    run.http_status = exc.status_code
    run.error_summary = str(exc)
    run.finished_at = now
    source.last_error_at = now
    source.last_error = str(exc)
    source.consecutive_failures += 1
    message = f"{source.display_name}: fetch failed ({exc})"
    if (
        isinstance(exc, SourceBlockedError)
        and source.consecutive_failures >= BLOCKED_DISABLE_THRESHOLD
    ):
        source.enabled = False
        source.last_error = f"{exc}. Disabled after {source.consecutive_failures} blocked attempts."
        message += ". Source disabled to respect the site; re-enable it manually."
    elif isinstance(exc, SourceNotFoundError):
        message += ". Check the board token."
    record_event(
        session,
        "task.failed",
        message,
        entity_type="source",
        entity_id=source.id,
        metadata={"http_status": exc.status_code, "run_id": run.id},
    )


def run_source(session: Session, source: Source, fetcher: Fetcher) -> RunSummary:
    """Fetch, normalize and persist one source. Commits; never raises fetch errors."""
    started = utcnow()
    minimum_minutes = {
        "remotive": 360,
        "jobicy": 60,
        "smartrecruiters": 60,
        "wwr": 60,
        "community": 120,
        "workday": 360,
    }.get(source.source_type)
    if minimum_minutes:
        previous = session.scalars(
            select(SourceRun)
            .where(SourceRun.source_id == source.id)
            .order_by(SourceRun.started_at.desc())
            .limit(1)
        ).first()
        if previous and (started - previous.started_at).total_seconds() < minimum_minutes * 60:
            record_event(
                session,
                "source.cached",
                "Provider refresh window is not due; using saved jobs.",
                entity_type="source",
                entity_id=source.id,
            )
            session.commit()
            return RunSummary(source.id, source.display_name, "skipped")
    adapter = ADAPTERS[source.source_type]
    run = SourceRun(source_id=source.id, started_at=started)
    session.add(run)
    session.flush()
    record_event(
        session,
        "run.started",
        f"Fetching {source.display_name}",
        entity_type="source",
        entity_id=source.id,
        metadata={"run_id": run.id},
    )
    session.commit()

    try:
        incremental = getattr(adapter, "fetch_raw_incremental", None)
        if incremental is not None:
            known = set(
                session.scalars(
                    select(JobSourceRecord.external_id).where(
                        JobSourceRecord.source_id == source.id
                    )
                )
            )
            raw_items, status = incremental(
                fetcher, source.board_token, source.rate_limit_seconds, known
            )
        else:
            raw_items, status = adapter.fetch_raw(
                fetcher, source.board_token, source.rate_limit_seconds
            )
    except (FetchError, InvalidPayloadError) as exc:
        err = exc if isinstance(exc, FetchError) else FetchError(str(exc))
        _fail(session, source, run, err, utcnow())
        session.commit()
        return RunSummary(source.id, source.display_name, "failed", error=str(err))

    # Reserve the writer before any normalization/upsert reads. Explicitly
    # beginning the parent transaction also prevents sqlite legacy savepoints
    # from committing individual rows when their outer transaction is implicit.
    session.execute(text("BEGIN IMMEDIATE"))
    now = utcnow()
    run.http_status = status
    run.fetched_count = len(raw_items)
    seen: set[str] = set()
    errors: list[str] = []
    company_name = source.display_name
    for i, raw in enumerate(raw_items, start=1):
        if i % 100 == 0:
            session.commit()  # keep write transactions short so the dashboard stays responsive
            session.execute(text("BEGIN IMMEDIATE"))
        raw_id = raw.get("id")
        if raw_id is not None:
            seen.add(str(raw_id))
        if raw.get("_seen_only"):
            # Already stored and still listed: refresh the sighting without refetching detail.
            _touch_seen(session, source, str(raw_id), now)
            continue
        try:
            nj = adapter.normalize(raw, company_name)
        except (InvalidPayloadError, ValidationError, TypeError, ValueError) as exc:
            run.invalid_count += 1
            if len(errors) < 5:
                errors.append(f"item {raw_id}: {type(exc).__name__}")
            continue
        with session.begin_nested():
            job, outcome = upsert_job(session, source, nj, now)
        if outcome in ("new", "possible_duplicate"):
            run.new_count += 1
            record_event(
                session,
                "job.ingested",
                f"New job: {job.title} ({source.display_name})",
                entity_type="job",
                entity_id=job.id,
                metadata={"possible_duplicate": outcome == "possible_duplicate"},
            )
        elif outcome == "duplicate":
            run.duplicate_count += 1
            record_event(
                session,
                "job.duplicate",
                f"Duplicate of existing job: {job.title}",
                entity_type="job",
                entity_id=job.id,
            )
        elif outcome == "updated":
            run.updated_count += 1

    run.closed_count = (
        0
        if run.invalid_count or source.source_type in PARTIAL_SNAPSHOT_TYPES
        else _close_unseen(session, source, seen, now)
    )
    run.status = "partial" if run.invalid_count else "success"
    run.error_summary = "; ".join(errors) or None
    run.finished_at = utcnow()
    source.last_success_at = run.finished_at
    source.consecutive_failures = 0
    source.last_error = None
    record_event(
        session,
        "source.fetch.completed",
        f"{source.display_name}: {run.fetched_count} fetched, {run.new_count} new, "
        f"{run.updated_count} updated, {run.duplicate_count} duplicate, "
        f"{run.invalid_count} invalid, {run.closed_count} closed",
        entity_type="source",
        entity_id=source.id,
        metadata={"run_id": run.id, "status": run.status},
    )
    session.commit()
    return RunSummary(
        source.id,
        source.display_name,
        run.status,
        run.fetched_count,
        run.new_count,
        run.updated_count,
        run.duplicate_count,
        run.invalid_count,
        run.closed_count,
        run.error_summary,
    )


def run_all(
    factory: sessionmaker[Session],
    fetcher: Fetcher,
    *,
    source_ids: list[str] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[RunSummary]:
    """Run every enabled source in its own session so one failure can't affect another."""
    with factory() as session:
        stmt = select(Source.id).where(Source.enabled.is_(True)).order_by(Source.display_name)
        ids = list(session.scalars(stmt))
    if source_ids is not None:
        ids = [i for i in ids if i in source_ids]
    results = []
    for sid in ids:
        if should_stop is not None and should_stop():
            break
        with factory() as session:
            source = session.get(Source, sid)
            if source is None:
                continue
            try:
                results.append(run_source(session, source, fetcher))
            except Exception as exc:  # isolate truly unexpected bugs per source
                logger.exception("Unexpected error ingesting source %s", sid)
                session.rollback()
                refreshed_source = session.get(Source, sid)
                unfinished = session.scalar(
                    select(SourceRun)
                    .where(SourceRun.source_id == sid, SourceRun.finished_at.is_(None))
                    .order_by(SourceRun.started_at.desc())
                    .limit(1)
                )
                if refreshed_source is not None and unfinished is not None:
                    _fail(
                        session,
                        refreshed_source,
                        unfinished,
                        FetchError(f"Unexpected ingestion error: {type(exc).__name__}"),
                        utcnow(),
                    )
                results.append(
                    RunSummary(
                        sid,
                        source.display_name,
                        "failed",
                        error=f"Unexpected error: {type(exc).__name__}",
                    )
                )
                record_event(
                    session,
                    "task.failed",
                    f"{source.display_name}: unexpected error ({type(exc).__name__})",
                    entity_type="source",
                    entity_id=sid,
                )
                session.commit()
    return results
