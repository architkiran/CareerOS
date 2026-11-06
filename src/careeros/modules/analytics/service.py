"""Funnel and conversion metrics, traceable to application events.

Every rate carries its sample size and a Wilson 95% interval. Recommendations
are only made when samples are large enough and intervals don't overlap;
otherwise we say there isn't enough data yet.
"""

import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from careeros.db.models import (
    Application,
    ApplicationEvent,
    Approval,
    Document,
    Job,
    JobSourceRecord,
    ResearchItem,
    RoleLane,
    Source,
)

PROGRESS = ("submitted", "response", "screen", "interview", "offer")
MIN_SAMPLE = 10
Z95 = 1.96


@dataclass(frozen=True)
class Rate:
    hits: int
    n: int

    @property
    def value(self) -> float | None:
        return self.hits / self.n if self.n else None

    @property
    def interval(self) -> tuple[float, float] | None:
        """Wilson score interval, sensible for small samples."""
        if not self.n:
            return None
        p, n, z = self.hits / self.n, self.n, Z95
        denom = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / denom
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
        return max(0.0, centre - half), min(1.0, centre + half)

    @property
    def small(self) -> bool:
        return self.n < MIN_SAMPLE


@dataclass
class FunnelStep:
    key: str
    label: str
    count: int
    from_previous: Rate | None


@dataclass
class Segment:
    name: str
    submitted: int
    response: Rate
    interview: Rate


@dataclass
class Analytics:
    funnel: list[FunnelStep]
    by_lane: list[Segment]
    by_source: list[Segment]
    by_week: list[Segment]
    median_days_to_submit: float | None
    median_days_to_response: float | None
    rejection_reasons: list[tuple[str, int]]
    outcomes: dict[str, int]
    recommendations: list[str] = field(default_factory=list)


def _reached(statuses: set[str]) -> set[str]:
    """Stages an application has reached, given every status it has held."""
    reached: set[str] = set()
    for i, stage in enumerate(PROGRESS):
        if any(s in statuses for s in PROGRESS[i:]):
            reached.add(stage)
    return reached


def _segments(rows: list[tuple[str, set[str]]]) -> list[Segment]:
    groups: dict[str, list[set[str]]] = defaultdict(list)
    for name, reached in rows:
        if "submitted" in reached:
            groups[name].append(reached)
    out = [
        Segment(
            name,
            len(apps),
            Rate(sum("response" in r for r in apps), len(apps)),
            Rate(sum("interview" in r for r in apps), len(apps)),
        )
        for name, apps in groups.items()
    ]
    return sorted(out, key=lambda s: (-s.submitted, s.name))


def _recommend(label: str, segments: list[Segment]) -> list[str]:
    big = [s for s in segments if not s.interview.small]
    if len(big) < 2:
        total = sum(s.submitted for s in segments)
        return (
            [
                f"{label}: not enough data to compare yet ({total} submitted; need at least "
                f"{MIN_SAMPLE} in two or more groups)."
            ]
            if segments
            else []
        )
    best = max(big, key=lambda s: s.interview.value or 0)
    worst = min(big, key=lambda s: s.interview.value or 0)
    bi, wi = best.interview.interval, worst.interview.interval
    assert bi and wi
    if best is worst or bi[0] <= wi[1]:
        return [f"{label}: no clear difference in interview rates yet (the ranges overlap)."]
    return [
        f"{label}: '{best.name}' converts to interviews more often than '{worst.name}' "
        f"({best.interview.hits}/{best.interview.n} vs "
        f"{worst.interview.hits}/{worst.interview.n}). "
        "Worth leaning into, but keep watching as more results come in."
    ]


def compute(session: Session) -> Analytics:
    from careeros.modules.matching.service import best_match_summary

    jobs = session.execute(select(Job.id, Job.triage_status, Job.triage_reason)).all()
    ranked = best_match_summary()
    passed = int(
        session.scalar(
            select(func.count())
            .select_from(ranked)
            .where(
                ranked.c.rank == 1, ranked.c.classified.is_(True), ranked.c.eligibility == "pass"
            )
        )
        or 0
    )
    apps = list(session.scalars(select(Application)))
    app_ids = [a.id for a in apps]
    statuses: dict[str, set[str]] = defaultdict(set)
    for ev in session.scalars(
        select(ApplicationEvent).where(ApplicationEvent.application_id.in_(app_ids))
    ):
        if ev.event_type.startswith("status:"):
            statuses[ev.application_id].add(ev.event_type.split(":", 1)[1])
    for a in apps:
        statuses[a.id].add(a.status)
    reached = {a.id: _reached(statuses[a.id]) for a in apps}

    shortlisted_ids = {j.id for j in jobs if j.triage_status == "shortlisted"} | {
        a.job_id for a in apps
    }
    researched = len(
        {
            r.job_id
            for r in session.scalars(select(ResearchItem).where(ResearchItem.status == "done"))
            if r.job_id
        }
    )
    prepared = len(
        {
            d.application_id
            for d in session.scalars(
                select(Document).where(
                    Document.document_type == "resume", Document.status == "ready"
                )
            )
        }
    )
    approved = len(
        {
            a.target_id
            for a in session.scalars(
                select(Approval).where(
                    Approval.action_type == "submit_application",
                    Approval.status.in_(("approved", "used")),
                )
            )
        }
    )
    counts = [
        ("discovered", "Discovered", len(jobs)),
        ("qualified", "Passed hard filters", passed),
        ("shortlisted", "Shortlisted", len(shortlisted_ids)),
        ("researched", "Researched", researched),
        ("prepared", "Documents ready", prepared),
        ("approved", "Approved", approved),
    ] + [(s, s.capitalize(), sum(s in r for r in reached.values())) for s in PROGRESS]
    funnel = [
        FunnelStep(k, label, c, Rate(c, counts[i - 1][2]) if i and counts[i - 1][2] else None)
        for i, (k, label, c) in enumerate(counts)
    ]

    lanes = {lane.id: lane.name for lane in session.scalars(select(RoleLane))}
    source_of: dict[str, str] = {}
    for job_id, name, source_type in session.execute(
        select(JobSourceRecord.job_id, Source.display_name, Source.source_type)
        .join(Source, Source.id == JobSourceRecord.source_id)
        .where(JobSourceRecord.job_id.in_([a.job_id for a in apps]))
        .order_by(JobSourceRecord.first_seen_at, JobSourceRecord.id)
    ):
        source_of.setdefault(job_id, f"{name} ({source_type})")

    def week(dt: datetime | None) -> str:
        if dt is None:
            return "unknown"
        y, w, _ = dt.isocalendar()
        return f"{y}-W{w:02d}"

    by_lane = _segments([(lanes.get(a.role_lane_id or "", "No lane"), reached[a.id]) for a in apps])
    by_source = _segments([(source_of.get(a.job_id, "Unknown"), reached[a.id]) for a in apps])
    by_week = sorted(
        _segments([(week(a.submitted_at), reached[a.id]) for a in apps]), key=lambda s: s.name
    )

    to_submit = [
        (a.submitted_at - a.created_at).total_seconds() / 86400 for a in apps if a.submitted_at
    ]
    first_response: list[float] = []
    for a in apps:
        if not a.submitted_at:
            continue
        evs = [
            e.occurred_at
            for e in session.scalars(
                select(ApplicationEvent).where(
                    ApplicationEvent.application_id == a.id,
                    ApplicationEvent.event_type.in_(
                        [f"status:{s}" for s in PROGRESS[1:]] + ["status:rejected"]
                    ),
                )
            )
        ]
        if evs:
            first_response.append((min(evs) - a.submitted_at).total_seconds() / 86400)

    reasons = Counter(
        (j.triage_reason or "").strip().lower()
        for j in jobs
        if j.triage_status == "rejected" and j.triage_reason
    )
    outcomes = Counter(a.outcome for a in apps if a.outcome)
    recs = _recommend("By lane", by_lane) + _recommend("By source", by_source)
    return Analytics(
        funnel=funnel,
        by_lane=by_lane,
        by_source=by_source,
        by_week=by_week,
        median_days_to_submit=round(statistics.median(to_submit), 1) if to_submit else None,
        median_days_to_response=round(statistics.median(first_response), 1)
        if first_response
        else None,
        rejection_reasons=reasons.most_common(8),
        outcomes=dict(outcomes),
        recommendations=recs,
    )
