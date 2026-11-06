"""Bounded, deterministic exploration. Job text is data, never executable instructions.

Findings expose actual postings and verified skill overlap. They do not claim
market-wide trends, employer sponsorship, lower competition or candidate eligibility.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import Company, Job, JobSourceRecord, MarketBrief, Source
from careeros.modules.events.service import record_event
from careeros.modules.market.contracts import MarketReport, PostingEvidence, RoleFinding
from careeros.modules.matching.service import best_matches
from careeros.modules.matching.text import contains_term
from careeros.modules.profile import service as profiles
from careeros.modules.sources.adapters.base import parse_epoch_ms, parse_iso


@dataclass(frozen=True)
class RoleTheme:
    key: str
    title: str
    titles: tuple[str, ...]
    skills: tuple[str, ...]
    explanation: str


THEMES = (
    RoleTheme(
        "analytics-engineering",
        "Analytics engineering",
        ("analytics engineer", "data transformation"),
        ("SQL", "Python", "dbt", "Snowflake"),
        "A bridge between analytical SQL and reliable "
        "data models; review modeling and tooling requirements.",
    ),
    RoleTheme(
        "financial-data-operations",
        "Financial data & reconciliation operations",
        (
            "reconciliation",
            "trade operations",
            "investment operations",
            "treasury analyst",
            "payment operations",
        ),
        ("SQL", "Python", "Excel", "DuckDB"),
        "Financial-data work connects reconciliation and analytics; assess "
        "your verified evidence and review domain requirements.",
    ),
    RoleTheme(
        "fraud-risk-analytics",
        "Fraud & risk analytics",
        ("fraud analyst", "risk analyst", "risk analytics", "fraud analytics", "financial crime"),
        ("SQL", "Python", "Excel", "Power BI"),
        "These postings connect analytical skills to risk "
        "decisions; domain experience and eligibility remain separate checks.",
    ),
    RoleTheme(
        "product-decision-analytics",
        "Product & decision analytics",
        (
            "product analyst",
            "product analytics",
            "growth analyst",
            "decision scientist",
            "decision analyst",
        ),
        ("SQL", "Python", "Tableau", "Power BI", "A/B testing"),
        "A cross-functional route from data analysis into "
        "product decisions; experimentation depth may need development.",
    ),
    RoleTheme(
        "data-quality",
        "Data quality & governance",
        ("data quality", "data governance", "data integrity", "data reliability"),
        ("SQL", "Python", "Excel", "dbt"),
        "Validation and KPI-standardization experience can transfer "
        "to data-quality work; review governance responsibilities.",
    ),
    RoleTheme(
        "business-systems",
        "Technical business & systems analysis",
        (
            "business systems analyst",
            "technical business analyst",
            "business intelligence engineer",
        ),
        ("SQL", "Python", "Excel", "Tableau", "Power BI"),
        "These titles combine stakeholder requirements with technical "
        "analysis; inspect each posting rather than assuming fit.",
    ),
    RoleTheme(
        "operations-analytics",
        "Operations & manufacturing analytics",
        (
            "quality analyst",
            "manufacturing analyst",
            "operations analytics",
            "supply chain analyst",
        ),
        ("SQL", "Python", "Excel", "Power BI", "DAX"),
        "Operational reporting can transfer across industries; the title "
        "alone does not verify manufacturing or domain expertise.",
    ),
    RoleTheme(
        "applied-data-science",
        "Applied data science",
        ("data scientist", "data science analyst"),
        ("Python", "SQL", "Pandas", "scikit-learn"),
        "Verified coding skills are an entry point, "
        "not proof of statistical or machine-learning qualifications.",
    ),
)


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def latest_brief(session: Session) -> MarketBrief | None:
    return session.scalars(
        select(MarketBrief).order_by(MarketBrief.created_at.desc()).limit(1)
    ).first()


def _source_date(record: JobSourceRecord, source: Source) -> tuple[datetime | None, str]:
    raw = record.raw_json
    if source.source_type == "greenhouse":
        return parse_iso(raw.get("first_published")), "publication_if_provided"
    if source.source_type == "ashby":
        return parse_iso(raw.get("publishedAt")), "publication_if_provided"
    if source.source_type == "lever":
        return parse_epoch_ms(raw.get("createdAt")), "source_creation"
    return None, "not_provided"


def generate_brief(
    session: Session,
    *,
    now: datetime | None = None,
    lookback_days: int = 7,
) -> MarketBrief:
    now = now or utcnow()
    if now.tzinfo is None or not 1 <= lookback_days <= 30:
        raise ValueError("Use a timezone-aware timestamp and a lookback from 1 to 30 days.")
    cutoff = now - timedelta(days=lookback_days)
    profile = profiles.get_profile(session)
    skills = (
        sorted({s.name for s in profiles.list_skills(session, profile.id, verified_only=True)})
        if profile
        else []
    )
    # Include the existing verified-profile input, not model assumptions.
    from careeros.modules.matching.service import build_profile_input

    profile_hash = _hash({"skills": skills, "profile": str(build_profile_input(session))})
    sources = list(session.scalars(select(Source).where(Source.enabled.is_(True))))
    enabled = sorted(source.id for source in sources)
    fresh = sorted(
        source.id
        for source in sources
        if source.last_success_at and cutoff <= source.last_success_at <= now
    )
    rows = session.execute(
        select(Job, Company.canonical_name)
        .join(Company)
        .where(
            Job.status == "active",
            Job.triage_status != "rejected",
            Job.last_seen_at >= cutoff,
            Job.last_seen_at <= now,
        )
        .order_by(Job.id)
    ).all()
    matches = best_matches(session, [job.id for job, _ in rows])
    records: dict[str, tuple[JobSourceRecord, Source]] = {}
    for rec, source in session.execute(
        select(JobSourceRecord, Source)
        .join(Source)
        .where(
            Source.enabled.is_(True),
            JobSourceRecord.last_seen_at >= cutoff,
            JobSourceRecord.last_seen_at <= now,
        )
        .order_by(JobSourceRecord.last_seen_at.desc())
    ):
        parsed = urlsplit(rec.source_url)
        if parsed.scheme in ("http", "https") and parsed.netloc and not parsed.username:
            records.setdefault(rec.job_id, (rec, source))
    eligible_rows = [(job, company) for job, company in rows if job.id in records]
    input_hash = _hash(
        {
            "version": "market-v1",
            "day": now.date().isoformat(),
            "profile": profile_hash,
            "sources": enabled,
            "fresh": fresh,
            "days": lookback_days,
            "failing_sources": sorted(source.id for source in sources if source.last_error),
            "jobs": [
                (
                    job.id,
                    job.last_seen_at,
                    job.description_hash,
                    matches[job.id].effective_score if job.id in matches else None,
                    matches[job.id].effective_eligibility if job.id in matches else None,
                )
                for job, _ in eligible_rows
            ],
        }
    )
    existing = session.scalars(
        select(MarketBrief).where(MarketBrief.input_hash == input_hash)
    ).first()
    if existing:
        return existing
    findings = []
    for theme in THEMES:
        evidence = []
        for job, company in eligible_rows:
            if not any(contains_term(job.title, term) for term in theme.titles):
                continue
            from careeros.modules.matching.seniority import infer_seniority

            guess = infer_seniority(job.title, job.description_text)
            if guess.confidence == "high" and guess.level in ("senior", "lead"):
                continue
            match = matches.get(job.id)
            if match and match.effective_eligibility == "fail":
                continue
            overlap = [skill for skill in skills if contains_term(job.description_text, skill)]
            if len(overlap) < 2:
                continue
            record, source = records[job.id]
            source_date, date_kind = _source_date(record, source)
            evidence.append(
                PostingEvidence(
                    job_id=job.id,
                    title=job.title,
                    company=company,
                    source_url=record.source_url,
                    source_name=source.display_name,
                    first_seen_at=job.first_seen_at,
                    last_seen_at=record.last_seen_at,
                    source_date=source_date,
                    source_date_kind=date_kind,
                    matched_verified_skills=overlap,
                    eligibility=match.effective_eligibility if match else "unknown",
                    fit_score=match.effective_score if match else None,
                )
            )
        if not evidence:
            continue
        evidence.sort(
            key=lambda item: (
                -(item.fit_score or 0),
                -len(item.matched_verified_skills),
                item.title,
            )
        )
        overlap = sorted({skill for item in evidence for skill in item.matched_verified_skills})
        findings.append(
            RoleFinding(
                key=theme.key,
                title=theme.title,
                explanation=theme.explanation,
                jobs=len(evidence),
                employers=len({item.company.casefold() for item in evidence}),
                verified_skills=overlap,
                additional_skills_to_review=[
                    s for s in theme.skills if s.casefold() not in {v.casefold() for v in skills}
                ],
                evidence=evidence[:5],
            )
        )
    findings.sort(key=lambda finding: (-finding.employers, -finding.jobs, finding.title))
    warnings = []
    if not skills:
        warnings.append(
            "No verified profile skills. Confirm your profile before exploring transferable roles."
        )
    if not enabled:
        warnings.append("No enabled sources. This report does not cover the wider job market.")
    if any(source.last_error for source in sources):
        warnings.append(
            "Some enabled sources currently report errors; "
            "check Sources before treating coverage as complete."
        )
    if len(fresh) < len(enabled):
        warnings.append(
            "Some enabled sources have not been refreshed successfully within this lookback window."
        )
    if not findings:
        warnings.append(
            "No evidence-backed role themes met the "
            "minimum verified-skill overlap in this snapshot."
        )
    report = MarketReport(
        generated_at=now,
        lookback_days=lookback_days,
        enabled_source_ids=enabled,
        fresh_source_ids=fresh,
        recent_active_jobs=len(eligible_rows),
        verified_skill_count=len(skills),
        findings=findings,
        warnings=warnings,
    )
    # A same-day repeat is never a trend baseline. Compare only stable source coverage.
    previous = session.scalars(
        select(MarketBrief)
        .where(
            MarketBrief.profile_hash == profile_hash,
            MarketBrief.created_at < now.replace(hour=0, minute=0, second=0, microsecond=0),
        )
        .order_by(MarketBrief.created_at.desc())
        .limit(1)
    ).first()
    if previous:
        before = MarketReport.model_validate(previous.report_json)
        if (
            before.enabled_source_ids == enabled
            and before.fresh_source_ids == fresh
            and before.lookback_days == lookback_days
            and before.algorithm_version == report.algorithm_version
        ):
            report.baseline_brief_id, report.baseline_at = previous.id, previous.created_at
            counts = {finding.key: finding.jobs for finding in before.findings}
            for finding in report.findings:
                finding.observed_change = finding.jobs - counts.get(finding.key, 0)
            report.trend_note = (
                "Changes compare two tracked-corpus snapshots with the same source coverage. "
                "They are not market-wide hiring rates or proof that a role is emerging."
            )
    brief = MarketBrief(
        created_at=now,
        input_hash=input_hash,
        profile_hash=profile_hash,
        report_json=report.model_dump(mode="json"),
    )
    # Establish a write transaction before the savepoint, then deduplicate concurrent requests.
    session.execute(
        update(MarketBrief)
        .where(MarketBrief.input_hash == input_hash)
        .values(input_hash=input_hash)
    )
    try:
        with session.begin_nested():
            session.add(brief)
            session.flush()
    except IntegrityError:
        return session.scalars(
            select(MarketBrief).where(MarketBrief.input_hash == input_hash)
        ).one()
    record_event(
        session,
        "market.brief_generated",
        f"Career intelligence: {len(findings)} role themes from "
        f"{len(eligible_rows)} recently observed postings.",
        entity_type="market_brief",
        entity_id=brief.id,
        metadata={"themes": len(findings), "source_count": len(enabled)},
    )
    return brief
