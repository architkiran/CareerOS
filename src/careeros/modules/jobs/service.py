"""Job inbox queries and user triage."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import Company, Job, JobSourceRecord, Source
from careeros.modules.events.service import record_event

if TYPE_CHECKING:
    from careeros.modules.matching.service import LaneMatchView

TriageAction = Literal["shortlist", "reject", "save", "reviewed", "reset"]
TRIAGE_STATUSES = ("new", "saved", "shortlisted", "reviewed", "rejected")
_ACTION_TO_STATUS = {
    "shortlist": "shortlisted",
    "reject": "rejected",
    "save": "saved",
    "reviewed": "reviewed",
    "reset": "new",
}
PAGE_SIZE = 50


class TriageError(ValueError):
    pass


@dataclass
class JobFilters:
    q: str | None = None
    triage: str | None = None
    status: Literal["active", "closed", "all"] = "active"
    source_id: str | None = None
    company_id: str | None = None
    workplace: str | None = None
    days: int | None = None
    possible_duplicates: bool = False
    lane_id: str | None = None
    eligibility: Literal["any", "pass", "unknown", "fail", "not_fail"] = "not_fail"
    min_score: int | None = None
    sort: Literal["newest", "score"] = "newest"
    page: int = 1
    recommended: bool = False
    published_minutes: int | None = None
    first_seen_after: datetime | None = None


@dataclass
class JobRow:
    job: Job
    company: str
    sources: list[str]
    match: "LaneMatchView | None" = None


def _filtered(filters: JobFilters) -> Select[Job, str]:
    stmt = select(Job, Company.canonical_name).join(Company, Company.id == Job.company_id)
    if filters.status != "all":
        stmt = stmt.where(Job.status == filters.status)
    if filters.triage:
        stmt = stmt.where(Job.triage_status == filters.triage)
    else:
        stmt = stmt.where(Job.triage_status != "rejected")  # hide rejected unless asked
    if filters.company_id:
        stmt = stmt.where(Job.company_id == filters.company_id)
    if filters.workplace:
        stmt = stmt.where(Job.workplace_type == filters.workplace)
    if filters.days:
        stmt = stmt.where(Job.first_seen_at >= utcnow() - timedelta(days=filters.days))
    if filters.published_minutes:
        now = utcnow()
        stmt = stmt.where(
            Job.posted_at >= now - timedelta(minutes=filters.published_minutes),
            Job.posted_at <= now,
        )
    if filters.first_seen_after:
        stmt = stmt.where(Job.first_seen_at > filters.first_seen_after)
    if filters.possible_duplicates:
        stmt = stmt.where(Job.possible_duplicate_of_id.is_not(None))
    if filters.source_id:
        stmt = stmt.where(
            Job.id.in_(
                select(JobSourceRecord.job_id).where(JobSourceRecord.source_id == filters.source_id)
            )
        )
    if filters.q:
        like = f"%{filters.q.strip()}%"
        stmt = stmt.where(
            or_(
                Job.title.ilike(like),
                Company.canonical_name.ilike(like),
                Job.description_text.ilike(like),
                Job.location_text.ilike(like),
            )
        )
    return stmt


def _match_for(
    session: Session, job_ids: list[str], lane_id: str | None
) -> dict[str, "LaneMatchView"]:
    from careeros.modules.matching.service import best_matches, lane_matches

    return lane_matches(session, job_ids, lane_id) if lane_id else best_matches(session, job_ids)


def list_jobs(session: Session, filters: JobFilters) -> tuple[list[JobRow], int]:
    """Filter/rank/page small columns in SQLite, then load evidence for one page only."""
    from careeros.modules.matching.service import best_match_summary

    ranked = best_match_summary(filters.lane_id)
    stmt = _filtered(filters).outerjoin(ranked, and_(ranked.c.job_id == Job.id, ranked.c.rank == 1))
    if filters.lane_id or filters.recommended:
        stmt = stmt.where(ranked.c.classified.is_(True))
    if filters.eligibility == "not_fail":
        stmt = stmt.where(or_(ranked.c.eligibility.is_(None), ranked.c.eligibility != "fail"))
    elif filters.eligibility in ("pass", "unknown", "fail"):
        stmt = stmt.where(ranked.c.eligibility == filters.eligibility)
    if filters.min_score is not None:
        stmt = stmt.where(ranked.c.score >= filters.min_score)
    total = (
        session.scalar(select(func.count()).select_from(stmt.with_only_columns(Job.id).subquery()))
        or 0
    )
    order = [Job.first_seen_at.desc(), Job.title, Job.id]
    if filters.sort == "score":
        order.insert(0, func.coalesce(ranked.c.score, -1).desc())
    page = max(filters.page, 1)
    rows = session.execute(
        stmt.order_by(*order).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    ).all()
    job_ids = [job.id for job, _ in rows]
    matches = _match_for(session, job_ids, filters.lane_id)
    names: dict[str, list[str]] = {}
    if job_ids:
        for job_id, name in session.execute(
            select(JobSourceRecord.job_id, Source.display_name + " (" + Source.source_type + ")")
            .join(Source, Source.id == JobSourceRecord.source_id)
            .where(JobSourceRecord.job_id.in_(job_ids))
        ):
            names.setdefault(job_id, []).append(name)
    return [
        JobRow(job, company, names.get(job.id, []), matches.get(job.id)) for job, company in rows
    ], int(total)


def recent_jobs(session: Session, limit: int = 5) -> list[JobRow]:
    """Bounded Mission Control feed with the same eligibility/override rules as the inbox."""
    from careeros.modules.matching.service import best_match_summary

    ranked = best_match_summary()
    rows = session.execute(
        select(Job, Company.canonical_name)
        .join(Company, Company.id == Job.company_id)
        .outerjoin(ranked, and_(ranked.c.job_id == Job.id, ranked.c.rank == 1))
        .where(
            Job.status == "active",
            Job.triage_status != "rejected",
            or_(ranked.c.eligibility.is_(None), ranked.c.eligibility != "fail"),
        )
        .order_by(Job.first_seen_at.desc(), Job.title, Job.id)
        .limit(max(1, min(limit, PAGE_SIZE)))
    ).all()
    ids = [job.id for job, _ in rows]
    matches = _match_for(session, ids, None)
    names: dict[str, list[str]] = {}
    if ids:
        for job_id, name in session.execute(
            select(JobSourceRecord.job_id, Source.display_name + " (" + Source.source_type + ")")
            .join(Source, Source.id == JobSourceRecord.source_id)
            .where(JobSourceRecord.job_id.in_(ids))
        ):
            names.setdefault(job_id, []).append(name)
    return [
        JobRow(job, company, names.get(job.id, []), matches.get(job.id)) for job, company in rows
    ]


@dataclass
class SourceSighting:
    source_name: str
    source_type: str
    external_id: str
    source_url: str
    first_seen_at: datetime
    last_seen_at: datetime


@dataclass
class JobDetail:
    job: Job
    company: Company
    sightings: list[SourceSighting]
    possible_duplicate_of: Job | None
    possible_duplicates: list[Job] = field(default_factory=list)


def get_job_detail(session: Session, job_id: str) -> JobDetail | None:
    job = session.get(Job, job_id)
    if job is None:
        return None
    company = session.get(Company, job.company_id)
    assert company is not None
    sightings = [
        SourceSighting(
            src.display_name,
            src.source_type,
            rec.external_id,
            rec.source_url,
            rec.first_seen_at,
            rec.last_seen_at,
        )
        for rec, src in session.execute(
            select(JobSourceRecord, Source)
            .join(Source, Source.id == JobSourceRecord.source_id)
            .where(JobSourceRecord.job_id == job.id)
            .order_by(JobSourceRecord.first_seen_at)
        )
    ]
    original = (
        session.get(Job, job.possible_duplicate_of_id) if job.possible_duplicate_of_id else None
    )
    dupes = list(session.scalars(select(Job).where(Job.possible_duplicate_of_id == job.id)))
    return JobDetail(job, company, sightings, original, dupes)


def triage(session: Session, job_id: str, action: TriageAction, reason: str | None = None) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise LookupError("Job not found")
    if action not in _ACTION_TO_STATUS:
        raise TriageError(f"Unknown action {action!r}")
    reason = (reason or "").strip() or None
    if action == "reject" and not reason:
        raise TriageError("Give a reason when rejecting a job, so patterns can be reviewed later.")
    if reason and len(reason) > 1000:
        raise TriageError("Reason is too long (1000 characters max).")
    job.triage_status = _ACTION_TO_STATUS[action]
    job.triage_reason = reason if action == "reject" else None
    job.triaged_at = utcnow() if action != "reset" else None
    if action == "shortlist":
        from careeros.modules.research.service import open_research

        open_research(session, job.id)
    record_event(
        session,
        "job.triaged",
        f"{job.title}: {job.triage_status}",
        entity_type="job",
        entity_id=job.id,
        metadata={"action": action},
    )
    return job


@dataclass
class JobCounts:
    new_today: int
    active: int
    shortlisted: int
    saved: int
    untriaged: int
    possible_duplicates: int


def job_counts(session: Session, display_timezone: str) -> JobCounts:
    tz = ZoneInfo(display_timezone)
    local_midnight = utcnow().astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)

    def count(*conds: object) -> int:
        return int(session.scalar(select(func.count()).select_from(Job).where(*conds)) or 0)  # type: ignore[arg-type]

    active = Job.status == "active"
    return JobCounts(
        new_today=count(Job.first_seen_at >= local_midnight),
        active=count(active),
        shortlisted=count(active, Job.triage_status == "shortlisted"),
        saved=count(active, Job.triage_status == "saved"),
        untriaged=count(active, Job.triage_status == "new"),
        possible_duplicates=count(
            active, Job.possible_duplicate_of_id.is_not(None), Job.triage_status == "new"
        ),
    )


def recommended_jobs(session: Session, limit: int = 3) -> list[JobRow]:
    rows, _ = list_jobs(session, JobFilters(recommended=True, sort="score", min_score=50))
    selected = []
    companies = set()
    for row in rows:
        if row.company in companies:
            continue
        selected.append(row)
        companies.add(row.company)
        if len(selected) >= limit:
            break
    return selected


def public_board_links(session: Session, job_ids: list[str]) -> dict[str, list[tuple[str, str]]]:
    """One query for original public-board attribution on any opportunity surface."""
    links: dict[str, list[tuple[str, str]]] = {}
    if job_ids:
        for job_id, kind, url in session.execute(
            select(JobSourceRecord.job_id, Source.source_type, JobSourceRecord.source_url)
            .join(Source, Source.id == JobSourceRecord.source_id)
            .where(
                JobSourceRecord.job_id.in_(job_ids),
                Source.source_type.in_(("remotive", "jobicy", "wwr")),
            )
        ):
            links.setdefault(job_id, []).append((kind, url))
    return links
