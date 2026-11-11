"""Read-only inbox projections: direct provenance links, concise evidence, and visit state."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import Application, Job, JobSourceRecord, RoleLane, Source
from careeros.modules.jobs.service import JobRow
from careeros.modules.jobs.sponsorship import LABELS, effective_state
from careeros.modules.sources.monitoring import coverage, discovery_busy, interval_minutes
from careeros.modules.sources.text import safe_posting_url
from careeros.modules.system.settings_store import get_setting, set_setting

AGGREGATORS = {"remotive", "jobicy", "wwr", "community"}
PROVIDER_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "smartrecruiters.com")


def _time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value)) if value else None
        return parsed if parsed and parsed.tzinfo is not None else None
    except ValueError:
        return None


def visit_cutoff(session: Session, *, navigation: bool) -> datetime | None:
    """A 30-minute visit window stays stable across pagination and passive polling."""
    now = utcnow()
    last_visit = _time(get_setting(session, "inbox.last_visit_at"))
    cutoff = _time(get_setting(session, "inbox.visit_cutoff"))
    if navigation:
        if last_visit is None or now - last_visit >= timedelta(minutes=30):
            cutoff = last_visit
            set_setting(session, "inbox.visit_cutoff", cutoff.isoformat() if cutoff else None)
        set_setting(session, "inbox.last_visit_at", now.isoformat())
    return cutoff


@dataclass(frozen=True)
class OriginalLink:
    url: str | None
    label: str
    source_name: str
    source_kind: str
    observed_at: datetime | None
    source_id: str | None = None


def original_links(session: Session, jobs: list[Job]) -> dict[str, OriginalLink]:
    records: dict[str, list[tuple[JobSourceRecord, Source]]] = defaultdict(list)
    if jobs:
        for rec, src in session.execute(
            select(JobSourceRecord, Source)
            .join(Source, Source.id == JobSourceRecord.source_id)
            .where(JobSourceRecord.job_id.in_([j.id for j in jobs]))
        ):
            records[rec.job_id].append((rec, src))
    result = {}
    for job in jobs:
        candidates = [
            (rec, src) for rec, src in records[job.id] if safe_posting_url(rec.source_url)
        ]

        def rank(pair: tuple[JobSourceRecord, Source]) -> tuple[int, int, float]:
            rec, src = pair
            host = (urlsplit(rec.source_url).hostname or "").lower()
            hosted = any(host == name or host.endswith("." + name) for name in PROVIDER_HOSTS)
            return (
                rec.is_listed is False,
                2
                if src.source_type in AGGREGATORS
                else 3
                if src.source_type == "manual"
                else 1
                if hosted
                else 0,
                -rec.last_seen_at.timestamp(),
            )

        candidates.sort(key=rank)
        if candidates:
            rec, src = candidates[0]
            label = (
                "View source posting" if src.source_type in AGGREGATORS else "View original posting"
            )
            result[job.id] = OriginalLink(
                rec.source_url, label, src.display_name, src.source_type, rec.last_seen_at, src.id
            )
        else:
            value = safe_posting_url(job.canonical_url)
            result[job.id] = OriginalLink(
                value,
                "View original posting" if value else "Original link unavailable",
                "Stored posting URL" if value else "No usable URL supplied",
                "unknown",
                None,
            )
    return result


@dataclass
class InboxCard:
    row: JobRow
    original: OriginalLink
    sponsorship: str
    sponsorship_label: str
    reasons: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    seniority: str | None = None
    freshness: list[str] = field(default_factory=list)
    publication: datetime | None = None
    publication_label: str = "Publication date unknown"
    app: Application | None = None
    saved_status: str = "Saved"


def cards(session: Session, rows: list[JobRow], cutoff: datetime | None = None) -> list[InboxCard]:
    jobs = [r.job for r in rows]
    links = original_links(session, jobs)
    apps = (
        {
            a.job_id: a
            for a in session.scalars(
                select(Application).where(Application.job_id.in_([j.id for j in jobs]))
            )
        }
        if jobs
        else {}
    )
    source_times = {s.id: s for s in coverage(session)}
    now = utcnow()
    result = []
    for row in rows:
        job, match = row.job, row.match
        state = effective_state(job, now)
        item = InboxCard(row, links[job.id], state, LABELS[state], app=apps.get(job.id))
        if job.posted_at and job.posted_at <= now and job.publication_kind == "original":
            item.publication = job.posted_at
            item.publication_label = {
                "original": "Published",
                "last_publication": "Last published (may be a repost)",
                "source_creation": "Source creation date",
                "provider_reported": "Provider date",
            }.get(job.publication_kind, "Source date")
        if (cutoff is None or job.first_seen_at > cutoff) and job.triage_status == "new":
            item.freshness.append("First found since your visit")
        if item.publication is None and job.first_seen_at >= now - timedelta(days=7):
            item.freshness.append("Recently discovered")
        if job.material_updated_at and (cutoff is None or job.material_updated_at > cutoff):
            item.freshness.append("Updated")
        if job.status == "closed":
            item.freshness.append("Closed")
        elif (item.original.observed_at or job.last_seen_at) < now - timedelta(
            minutes=(
                source_times[item.original.source_id].minutes * 2
                if item.original.source_id in source_times
                else 60
            )
        ):
            item.freshness.append("Possibly stale")
        if job.possible_duplicate_of_id:
            item.freshness.append("Possible repost")
        if match and match.match.classified:
            breakdown = match.match.score_breakdown_json
            skill_names = breakdown.get("matched_skills", [])[:3]
            if skill_names:
                item.reasons.append("Verified skill overlap: " + ", ".join(skill_names))
            item.reasons.append("Role family: " + match.lane_name)
            item.seniority = breakdown.get("seniority", {}).get("level")
            item.concerns = [
                str(c["reason"])
                for c in match.match.hard_filter_results_json
                if c.get("decision") != "pass"
            ]
        else:
            item.reasons.append("Matching not available yet; inspect the source requirements.")
        item.reasons.append("Sponsorship: " + item.sponsorship_label.lower())
        item.reasons = item.reasons[:3]
        if item.app and item.app.submitted_at:
            item.saved_status = "Rejected" if item.app.status == "rejected" else "Applied"
        elif job.status == "closed":
            item.saved_status = "Closed"
        else:
            item.saved_status = {"reviewing": "Reviewing", "rejected": "Rejected"}.get(
                job.saved_stage or "", "Saved"
            )
        result.append(item)
    return result


def refresh_overview(session: Session) -> dict[str, object]:
    from careeros.db.models import Task

    rows = coverage(session)
    now = utcnow()
    sources = list(
        session.scalars(
            select(Source).where(Source.source_type != "manual", Source.enabled.is_(True))
        )
    )
    latest = max((s.last_success_at for s in sources if s.last_success_at), default=None)
    heartbeat = _time(get_setting(session, "worker.last_seen_at"))
    return {
        "enabled": get_setting(session, "watch.enabled", True),
        "interval": interval_minutes(session),
        "last_success": latest,
        "next_due": min((r.next_due for r in rows), default=None),
        "errors": [s for s in sources if s.last_error],
        "stale": [
            r
            for r in rows
            if r.checked is None or now - r.checked > timedelta(minutes=r.minutes * 2)
        ],
        "partial": [r for r in rows if r.state in ("Some items rejected", "Interrupted")],
        "busy": discovery_busy(session)
        or bool(
            session.scalar(
                select(Task.id)
                .where(Task.task_type == "match.all", Task.status.in_(("queued", "running")))
                .limit(1)
            )
        ),
        "worker_recent": heartbeat is not None and now - heartbeat < timedelta(seconds=75),
        "source_count": len(rows),
    }


def has_lanes(session: Session) -> bool:
    return (
        session.scalar(select(RoleLane.id).where(RoleLane.enabled.is_(True)).limit(1)) is not None
    )


def counts(session: Session, cutoff: datetime | None) -> dict[str, int]:
    from careeros.modules.jobs.service import JobFilters, count_jobs

    new = count_jobs(
        session,
        JobFilters(
            recommended=has_lanes(session),
            unreviewed=True,
            first_seen_after=cutoff,
            exclude_applied=True,
        ),
    )
    saved = (
        session.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                (Job.saved_stage.is_not(None)) | (Job.triage_status.in_(("saved", "shortlisted")))
            )
        )
        or 0
    )
    applied = (
        session.scalar(
            select(func.count())
            .select_from(Application)
            .where(Application.submitted_at.is_not(None))
        )
        or 0
    )
    return {"new": new, "saved": saved, "applied": applied}
