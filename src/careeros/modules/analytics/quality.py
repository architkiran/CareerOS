"""Decision-oriented quality metrics with explicit denominators and unknown link availability."""

import statistics
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import ActivityEvent, Application, ApplicationEvent, Job, JobSourceRecord
from careeros.modules.analytics.service import Rate
from careeros.modules.matching.service import best_match_summary
from careeros.modules.sources.text import safe_posting_url


def compute_quality(session: Session) -> dict[str, Any]:
    now = utcnow()
    rows = session.execute(
        select(
            Job.id,
            Job.posted_at,
            Job.publication_kind,
            Job.first_seen_at,
            Job.canonical_url,
            Job.possible_duplicate_of_id,
        )
    ).all()
    valid_destinations = {r.id for r in rows if safe_posting_url(r.canonical_url)}
    for job_id, url in session.execute(select(JobSourceRecord.job_id, JobSourceRecord.source_url)):
        if safe_posting_url(url):
            valid_destinations.add(job_id)
    lags = [
        (r.first_seen_at - r.posted_at).total_seconds() / 60
        for r in rows
        if r.publication_kind == "original"
        and r.posted_at
        and r.posted_at <= r.first_seen_at <= now
    ]
    events = list(
        session.scalars(
            select(ActivityEvent)
            .where(ActivityEvent.created_at >= now - timedelta(days=7))
            .order_by(ActivityEvent.id)
        )
    )
    counts: Counter[str] = Counter()
    reviews: dict[str, str] = {}
    application_scores: dict[str, int | None] = {}
    for event in events:
        if event.event_type == "job.original_opened":
            counts["opened"] += 1
        elif event.event_type == "application.manually_recorded":
            counts["applied"] += 1
        elif event.event_type == "job.triaged":
            key = {"save": "saved", "reject": "dismissed", "reviewed": "reviewed"}.get(
                str(event.metadata_json.get("action", ""))
            )
            if key:
                counts[key] += 1
        elif event.event_type == "job.page_reviewed":
            counts["reviewed"] += int(event.metadata_json.get("count", 0))
        elif event.event_type == "job.eligibility_review" and event.entity_id:
            reviews[event.entity_id] = str(event.metadata_json.get("decision"))
    # Use recorded application-time scores, never today’s reconstructed ranking.
    for event in session.scalars(
        select(ActivityEvent).where(ActivityEvent.event_type == "application.manually_recorded")
    ):
        value = event.metadata_json.get("match_score")
        if event.entity_id:
            application_scores[event.entity_id] = value if isinstance(value, int) else None
    progressed = {
        ev.application_id
        for ev in session.scalars(
            select(ApplicationEvent).where(
                ApplicationEvent.event_type.in_(
                    ("status:screen", "status:interview", "status:offer")
                )
            )
        )
    }
    bands: dict[str, list[bool]] = defaultdict(list)
    for app in session.scalars(select(Application).where(Application.submitted_at.is_not(None))):
        score = application_scores.get(app.id)
        band = (
            "Not recorded"
            if score is None
            else "80–100"
            if score >= 80
            else "60–79"
            if score >= 60
            else "0–59"
        )
        bands[band].append(app.id in progressed or app.status in ("screen", "interview", "offer"))
    ranked = best_match_summary()
    recent = session.scalars(
        select(Job.first_seen_at)
        .join(ranked, and_(ranked.c.job_id == Job.id, ranked.c.rank == 1))
        .where(
            Job.first_seen_at >= now - timedelta(days=7),
            ranked.c.classified.is_(True),
            ranked.c.eligibility != "fail",
        )
    )
    days = Counter(
        value.astimezone(ZoneInfo("America/New_York")).date().isoformat() for value in recent
    )
    return {
        "relevant_by_day": sorted(days.items()),
        "jobs": len(rows),
        "valid_urls": len(valid_destinations),
        "url_availability": None,
        "publication_delay_minutes": round(statistics.median(lags), 1) if lags else None,
        "publication_delay_n": len(lags),
        "possible_duplicates": sum(bool(r.possible_duplicate_of_id) for r in rows),
        "decisions": counts,
        "eligibility_review": Rate(sum(v == "fits" for v in reviews.values()), len(reviews)),
        "review_uncertain": sum(v == "unsure" for v in reviews.values()),
        "by_match_band": [
            (name, Rate(sum(values), len(values))) for name, values in sorted(bands.items())
        ],
    }
