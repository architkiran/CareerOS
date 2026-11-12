"""Evaluate stored jobs, persist one verdict each, and assemble the daily digest."""

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import (
    Application,
    CandidateProfile,
    CandidateSkill,
    Company,
    Job,
    JobSourceRecord,
    JobVerdict,
    Skill,
    Source,
    SourceRun,
    WorkAuthorizationProfile,
)
from careeros.db.models.jobs import AGGREGATOR_TYPES
from careeros.modules.eligibility.engine import (
    ENGINE_VERSION,
    CandidateRules,
    JobFacts,
    classify_role,
    evaluate,
)
from careeros.modules.outreach.kit import DEFAULT_INTRO, build_kit
from careeros.modules.sources.text import normalize_key
from careeros.modules.sponsorship import lca
from careeros.modules.sponsorship.levels import LcaSummary, assess
from careeros.modules.system.settings_store import get_setting

BUCKETS = ("eligible", "research", "review")
LEVEL_ORDER = {"A": 0, "B": 1, "C": 2, "U": 3, "D": 4}


def candidate_rules(session: Session) -> CandidateRules:
    profile = session.scalars(select(CandidateProfile).limit(1)).first()
    needs: bool | None = None
    relocation: bool | None = None
    skills: tuple[str, ...] = ()
    if profile is not None:
        auth = session.scalars(
            select(WorkAuthorizationProfile).where(
                WorkAuthorizationProfile.profile_id == profile.id
            )
        ).first()
        if auth is not None and auth.verified_at is not None:
            answers = {auth.requires_sponsorship_now, auth.requires_sponsorship_future}
            needs = True if "yes" in answers else False if answers == {"no"} else None
        prefs = profile.relocation_preferences_json or {}
        if isinstance(prefs, dict) and isinstance(prefs.get("open_to_relocation"), bool):
            relocation = prefs["open_to_relocation"]
        skills = tuple(
            session.scalars(
                select(Skill.canonical_name)
                .join(CandidateSkill, CandidateSkill.skill_id == Skill.id)
                .where(
                    CandidateSkill.profile_id == profile.id,
                    CandidateSkill.verified_status == "verified",
                )
            )
        )
    return CandidateRules(
        needs_sponsorship=needs, open_to_relocation=relocation, verified_skills=skills
    )


def _upsert_verdicts(session: Session, rows: list[dict[str, Any]]) -> None:
    """Write verdicts so that two evaluators (CLI and worker) can overlap safely.

    A plain insert raced: both saw "no verdict yet" and the second insert broke the primary
    key. The upsert makes the last evaluation win, which is correct because both are
    computed from the same stored job.
    """
    if not rows:
        return
    statement = sqlite_insert(JobVerdict).values(rows)
    updates = {
        c.name: statement.excluded[c.name]
        for c in JobVerdict.__table__.columns
        if c.name != "job_id"
    }
    session.execute(statement.on_conflict_do_update(index_elements=["job_id"], set_=updates))
    for loaded in list(session.identity_map.values()):
        if isinstance(loaded, JobVerdict):
            session.expire(loaded)  # the row changed underneath any object read earlier
    rows.clear()


@dataclass
class EvaluationSummary:
    evaluated: int = 0
    by_verdict: Counter[str] = field(default_factory=Counter)
    by_level: Counter[str] = field(default_factory=Counter)
    rejected_reasons: Counter[str] = field(default_factory=Counter)
    lca_loaded: bool = False


def evaluate_all(
    session: Session, now: datetime | None = None, company_id: str | None = None
) -> EvaluationSummary:
    """Evaluate every stored job, or only one employer's jobs after its evidence changed."""
    now = now or utcnow()
    aliases = lca.confirmed_aliases(session)
    rules = candidate_rules(session)
    summary = EvaluationSummary(lca_loaded=lca.has_data(session))
    sightings: dict[str, list[tuple[str, str, dict[str, Any], datetime]]] = defaultdict(list)
    for job_id, kind, url, raw, seen in session.execute(
        select(
            JobSourceRecord.job_id,
            Source.source_type,
            JobSourceRecord.source_url,
            JobSourceRecord.raw_json,
            JobSourceRecord.last_seen_at,
        ).join(Source, Source.id == JobSourceRecord.source_id)
    ):
        sightings[job_id].append((kind, url, raw if isinstance(raw, dict) else {}, seen))
    companies = dict(session.execute(select(Company.id, Company.canonical_name)).all())
    lca_cache: dict[str, LcaSummary | None] = {}
    pending: list[dict[str, Any]] = []
    jobs = select(Job) if company_id is None else select(Job).where(Job.company_id == company_id)
    for job in session.scalars(jobs):
        company = companies.get(job.company_id, "")
        seen = sightings.get(job.id, [])
        official = any(kind not in AGGREGATOR_TYPES for kind, *_ in seen)
        feed = next((s for s in seen if s[0] == "community"), None)
        family, _ = classify_role(job.title)
        company_lca = None
        if summary.lca_loaded and (family or "analyst" in job.title.lower()):
            if company not in lca_cache:
                lca_cache[company] = lca.lookup(session, company, aliases)
            company_lca = lca_cache[company]
        sponsorship = assess(
            description=job.description_text or "",
            posting_url=job.canonical_url,
            posting_is_official=official,
            observed_at=job.last_seen_at.date().isoformat(),
            feed_flag=str(feed[2].get("sponsorship")) if feed else None,
            feed_name="SimplifyJobs New-Grad-Positions (community list)" if feed else None,
            lca=company_lca,
        )
        facts = JobFacts(
            title=job.title,
            company=company,
            location_text=job.location_text,
            workplace_type=job.workplace_type,
            employment_type=job.employment_type,
            description=job.description_text or "",
            status=job.status,
            last_seen_at=job.last_seen_at,
            posted_at=job.posted_at,
            first_seen_at=job.first_seen_at,
            has_official_source=official,
            on_new_grad_list=feed is not None,
        )
        result = evaluate(facts, rules, sponsorship, now)
        pending.append(
            {
                "job_id": job.id,
                "verdict": result.verdict,
                "sponsorship_level": result.sponsorship_level,
                "fit": result.fit,
                "role_family": result.role_family,
                "reason": result.reason,
                "next_action": result.next_action,
                "checks_json": result.checks_json(),
                "sponsorship_json": sponsorship.to_dict(),
                "fit_json": {
                    "reasons": list(result.fit_reasons),
                    "gaps": list(result.gaps),
                    "flags": list(result.flags),
                    "family_label": result.role_family_label,
                },
                "rank": result.rank,
                "engine_version": ENGINE_VERSION,
                "evaluated_at": now,
            }
        )
        if len(pending) >= 200:
            _upsert_verdicts(session, pending)
        summary.evaluated += 1
        summary.by_verdict[result.verdict] += 1
        if result.verdict != "rejected":
            summary.by_level[result.sponsorship_level] += 1
        else:
            summary.rejected_reasons[result.reason.split(":")[0]] += 1
    _upsert_verdicts(session, pending)
    return summary


FRESH_ORDER = {"today": 0, "week": 1, "earlier": 2, "older": 3}
FRESH_LABEL = {
    "today": "Posted in the last 24 hours",
    "week": "This week",
    "earlier": "Earlier this month",
    "older": "Older than 30 days",
}


def freshness(
    posted_at: datetime | None, first_seen_at: datetime, now: datetime
) -> tuple[int, str, bool, str]:
    """(age in hours, short label, publication date known?, band).

    When the source gives no publication date the age is counted from our first sighting,
    which can only understate it, so the card says the true date is unknown.
    """
    known = posted_at is not None
    hours = max(int((now - (posted_at or first_seen_at)).total_seconds() // 3600), 0)
    label = f"{hours}h" if hours < 24 else f"{hours // 24}d"
    band = "today" if hours < 24 else "week" if hours < 168 else "earlier"
    if hours >= 720:
        band = "older"
    return hours, label, known, band


@dataclass
class Card:
    job_id: str
    title: str
    company: str
    location: str | None
    url: str
    verdict: str
    level: str
    level_label: str
    fit: str | None
    family: str | None
    reason: str
    next_action: str
    checks: list[dict[str, Any]]
    sponsorship: dict[str, Any]
    fit_reasons: list[str]
    gaps: list[str]
    flags: list[str]
    posted_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    official: bool
    saved_stage: str | None
    outreach: dict[str, Any] = field(default_factory=dict)
    applied: bool = False
    rank: int = 0
    age_hours: int = 0
    age_label: str = ""
    age_known: bool = True  # False when only our first sighting is known
    fresh: str = "earlier"  # today | week | earlier | older


@dataclass
class Digest:
    generated_at: datetime
    eligible: list[Card]
    research: list[Card]
    review: list[Card]
    counts: dict[str, int]
    rejected_reasons: list[tuple[str, int]]
    sources_ok: int
    sources_failing: list[str]
    last_success_at: datetime | None
    lca_loaded: bool
    sponsorship_confirmed: bool


def build_digest(
    session: Session, *, limit: int = 150, family: str | None = None, now: datetime | None = None
) -> Digest:
    now = now or utcnow()
    official_jobs = set(
        session.scalars(
            select(JobSourceRecord.job_id)
            .join(Source, Source.id == JobSourceRecord.source_id)
            .where(Source.source_type.not_in(AGGREGATOR_TYPES))
        )
    )
    rows = session.execute(
        select(JobVerdict, Job, Company.canonical_name)
        .join(Job, Job.id == JobVerdict.job_id)
        .join(Company, Company.id == Job.company_id)
        .where(
            JobVerdict.verdict.in_(BUCKETS),
            Job.status == "active",
            Job.triage_status != "rejected",
        )
        .order_by(JobVerdict.rank.desc(), Job.posted_at.desc().nullslast())
    ).all()
    profile = session.scalars(select(CandidateProfile).limit(1)).first()
    name = profile.display_name if profile is not None else ""
    school = get_setting(session, "outreach.school")
    intro = get_setting(session, "outreach.intro") or DEFAULT_INTRO
    applied_jobs = set(
        session.scalars(select(Application.job_id).where(Application.submitted_at.is_not(None)))
    )
    buckets: dict[str, list[Card]] = {b: [] for b in BUCKETS}
    seen_keys: dict[tuple[str, str], Card] = {}
    for verdict, job, company in rows:
        if family and verdict.role_family != family:
            continue
        card = Card(
            job_id=job.id,
            title=job.title,
            company=company,
            location=job.location_text,
            url=job.canonical_url,
            verdict=verdict.verdict,
            level=verdict.sponsorship_level,
            level_label=str(verdict.sponsorship_json.get("label", "")),
            fit=verdict.fit,
            family=str(verdict.fit_json.get("family_label") or "") or None,
            reason=verdict.reason,
            next_action=verdict.next_action,
            checks=list(verdict.checks_json),
            sponsorship=dict(verdict.sponsorship_json),
            fit_reasons=list(verdict.fit_json.get("reasons", [])),
            gaps=list(verdict.fit_json.get("gaps", [])),
            flags=list(verdict.fit_json.get("flags", [])),
            posted_at=job.posted_at,
            first_seen_at=job.first_seen_at,
            last_seen_at=job.last_seen_at,
            official=job.id in official_jobs,
            saved_stage=job.saved_stage,
            applied=job.id in applied_jobs,
            rank=verdict.rank,
        )
        card.outreach = build_kit(
            company=company,
            title=job.title,
            family_label=card.family,
            recruiter_question=card.sponsorship.get("recruiter_question"),
            candidate_name=name,
            school=school if isinstance(school, str) and school else None,
            intro=str(intro),
        )
        card.age_hours, card.age_label, card.age_known, card.fresh = freshness(
            job.posted_at, job.first_seen_at, now
        )
        # The same role can arrive from a community list and the employer's ATS under
        # different URLs. Show it once, preferring the employer-verified record.
        key = (normalize_key(company), normalize_key(job.title))
        kept = seen_keys.get(key)
        if kept is not None:
            if card.official and not kept.official:
                buckets[kept.verdict].remove(kept)
            else:
                continue
        seen_keys[key] = card
        buckets[card.verdict].append(card)
    counts = dict(
        session.execute(select(JobVerdict.verdict, func.count()).group_by(JobVerdict.verdict)).all()
    )
    for cards in buckets.values():
        # Freshest first; the fit rank only orders roles of the same age band.
        cards.sort(key=lambda c: (FRESH_ORDER[c.fresh], -c.rank, c.age_hours))
    counts["shown_eligible"] = len(buckets["eligible"])
    counts["shown_research"] = len(buckets["research"])
    counts["shown_review"] = len(buckets["review"])
    reasons: Counter[str] = Counter()
    for (reason,) in session.execute(
        select(JobVerdict.reason).where(JobVerdict.verdict == "rejected")
    ):
        reasons[reason.split(":")[0]] += 1
    sources = list(session.scalars(select(Source).where(Source.enabled.is_(True))))
    failing = [s.display_name for s in sources if s.consecutive_failures > 0]
    last_success = session.scalar(
        select(func.max(SourceRun.finished_at)).where(SourceRun.status.in_(("success", "partial")))
    )
    rules = candidate_rules(session)
    return Digest(
        generated_at=now,
        eligible=buckets["eligible"][:limit],
        research=buckets["research"][:limit],
        review=buckets["review"][:limit],
        counts=counts,
        rejected_reasons=reasons.most_common(8),
        sources_ok=len(sources) - len(failing),
        sources_failing=failing[:12],
        last_success_at=last_success,
        lca_loaded=lca.has_data(session),
        sponsorship_confirmed=rules.needs_sponsorship is not None,
    )


def _age(card: Card, now: datetime) -> str:
    if card.posted_at is not None:
        days = max((now - card.posted_at).days, 0)
        return f"published {days}d ago"
    days = max((now - card.first_seen_at).days, 0)
    return f"first seen {days}d ago (publication date unknown)"


def digest_markdown(digest: Digest) -> str:
    now = digest.generated_at
    lines = [
        f"# Career OS daily digest, {now:%Y-%m-%d}",
        "",
        f"- Eligible (all hard rules pass, sponsorship Level A or B): **{len(digest.eligible)}**",
        f"- Sponsorship research queue (Level C or U): **{len(digest.research)}**",
        f"- Needs your review (a hard criterion is unknown): **{len(digest.review)}**",
        f"- Rejected and kept for audit: {digest.counts.get('rejected', 0)}",
        f"- Sources healthy: {digest.sources_ok}; failing: "
        + (", ".join(digest.sources_failing) or "none"),
    ]
    if not digest.lca_loaded:
        lines.append(
            "- **LCA data not imported**, so no employer can reach Level B yet. "
            "See docs/SPONSORSHIP_EVIDENCE.md."
        )
    if not digest.sponsorship_confirmed:
        lines.append("- **Your sponsorship need is unconfirmed in the profile.**")
    if not digest.eligible:
        lines += ["", "No verified eligible roles today. Nothing has been padded in."]

    def section(title: str, cards: list[Card], cap: int) -> None:
        if not cards:
            return
        lines.extend(["", f"## {title}", ""])
        for c in cards[:cap]:
            lines.append(f"### {c.title} · {c.company}")
            lines.append(
                f"{c.location or 'Location not stated'} · {_age(c, now)} · fit: {c.fit} · "
                f"sponsorship Level {c.level} ({c.level_label})"
            )
            lines.append(f"Original posting: {c.url}")
            for reason in c.fit_reasons[:3]:
                lines.append(f"- {reason}")
            for item in c.sponsorship.get("items", [])[:2]:
                quote = f' "{item["quote"]}"' if item.get("quote") else ""
                lines.append(f"- Evidence ({item['source_name']}): {item['claim']}{quote}")
            for flag in c.flags[:2]:
                lines.append(f"- Note: {flag}")
            lines.append(f"- Next: {c.next_action}")
            lines.append("")

    section("Eligible", digest.eligible, 15)
    section("Sponsorship research queue (unverified)", digest.research, 15)
    section("Needs your review", digest.review, 10)
    if digest.rejected_reasons:
        lines += ["", "## Why roles were rejected", ""]
        lines += [f"- {reason}: {n}" for reason, n in digest.rejected_reasons]
    return "\n".join(lines) + "\n"


def recent_window(cards: list[Card], now: datetime, days: int = 2) -> list[Card]:
    cutoff = now - timedelta(days=days)
    return [c for c in cards if c.first_seen_at >= cutoff]


def card_dict(card: Card) -> dict[str, Any]:
    return asdict(card)
