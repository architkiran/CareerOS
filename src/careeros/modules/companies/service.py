from dataclasses import dataclass

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from careeros.db.models import (
    Application,
    Company,
    Evidence,
    Job,
    JobSourceRecord,
    ResearchItem,
    Source,
)
from careeros.modules.events.service import record_event
from careeros.modules.ingestion.service import get_or_create_company
from careeros.modules.research import service as research
from careeros.modules.system.settings_store import get_setting


@dataclass
class CompanyRow:
    company: Company
    active_jobs: int
    watchlist: bool


def watchlist_names(session: Session) -> list[str]:
    preferences = get_setting(session, "career.preferences", {})
    values = preferences.get("target_companies", []) if isinstance(preferences, dict) else []
    return (
        [
            value.strip()
            for value in values[:50]
            if isinstance(value, str) and 0 < len(value.strip()) <= 200
        ]
        if isinstance(values, list)
        else []
    )


def open_company_research(session: Session, company_id: str) -> ResearchItem:
    session.execute(update(Company).where(Company.id == company_id).values(id=company_id))
    if session.get(Company, company_id) is None:
        raise LookupError("Company not found")
    existing = session.scalars(
        select(ResearchItem).where(
            ResearchItem.company_id == company_id,
            ResearchItem.job_id.is_(None),
            ResearchItem.research_type == "company_intelligence",
        )
    ).first()
    if existing:
        return existing
    item = ResearchItem(
        company_id=company_id,
        research_type="company_intelligence",
        summary="Company research workspace. Review sourced facts and role-specific eligibility; "
        "unknowns remain unknown.",
    )
    session.add(item)
    session.flush()
    record_event(
        session,
        "company.research_opened",
        "Company research workspace opened.",
        entity_type="company",
        entity_id=company_id,
    )
    return item


def ensure_watchlist(session: Session) -> int:
    """Prepare local workspaces only. A watchlist preference never verifies sponsorship."""
    created = 0
    for name in watchlist_names(session):
        company = get_or_create_company(session, name)
        existing = session.scalars(
            select(ResearchItem.id).where(
                ResearchItem.company_id == company.id,
                ResearchItem.job_id.is_(None),
                ResearchItem.research_type == "company_intelligence",
            )
        ).first()
        open_company_research(session, company.id)
        created += existing is None
    return created


def list_companies(session: Session) -> list[CompanyRow]:
    names = watchlist_names(session)
    order = {name.casefold(): index for index, name in enumerate(names)}
    counts = dict(
        session.execute(
            select(Job.company_id, func.count())
            .where(Job.status == "active")
            .group_by(Job.company_id)
        ).all()
    )
    rows = [
        CompanyRow(
            company, int(counts.get(company.id, 0)), company.canonical_name.casefold() in order
        )
        for company in session.scalars(select(Company).order_by(Company.canonical_name))
    ]
    return sorted(
        rows,
        key=lambda row: (
            not row.watchlist,
            order.get(row.company.canonical_name.casefold(), 999),
            row.company.canonical_name,
        ),
    )


def workspace(session: Session, company_id: str) -> dict[str, object]:
    company = session.get(Company, company_id)
    if company is None:
        raise LookupError("Company not found")
    counts = int(
        session.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.company_id == company.id, Job.status == "active")
        )
        or 0
    )
    applications = int(
        session.scalar(
            select(func.count())
            .select_from(Application)
            .join(Job)
            .where(Job.company_id == company.id)
        )
        or 0
    )
    jobs = list(
        session.scalars(
            select(Job)
            .where(Job.company_id == company.id, Job.status == "active")
            .order_by(Job.first_seen_at.desc())
            .limit(10)
        )
    )
    source_ids = select(JobSourceRecord.source_id).join(Job).where(Job.company_id == company.id)
    sources = list(
        session.scalars(
            select(Source)
            .where(or_(Source.company_id == company.id, Source.id.in_(source_ids)))
            .order_by(Source.display_name)
        )
    )
    item = session.scalars(
        select(ResearchItem).where(
            ResearchItem.company_id == company.id,
            ResearchItem.job_id.is_(None),
            ResearchItem.research_type == "company_intelligence",
        )
    ).first()
    evidence = list(
        session.scalars(
            select(Evidence)
            .where(Evidence.company_id == company.id, Evidence.job_id.is_(None))
            .order_by(Evidence.created_at.desc())
        )
    )
    return {
        "company": company,
        "tracked_jobs": counts,
        "applications": applications,
        "jobs": jobs,
        "sources": sources,
        "item": item,
        "evidence": evidence,
        "policy": research.employer_policy(session, company.id),
        "claim_labels": research.CLAIM_LABELS,
        "age_days": research.evidence_age_days,
    }


def add_research_lead(session: Session, company_id: str, data: research.EvidenceIn) -> Evidence:
    """Assistant-collected research is a pending lead, never user-confirmed evidence."""
    existing = session.scalars(
        select(Evidence).where(
            Evidence.company_id == company_id,
            Evidence.job_id.is_(None),
            Evidence.source_url == data.source_url,
            Evidence.claim_text == data.claim_text,
            Evidence.claim_type == data.claim_type,
        )
    ).first()
    if existing:
        return existing
    item = open_company_research(session, company_id)
    draft = research.add_evidence(session, item.id, data.model_copy(update={"checked": False}))
    draft.origin = "research"
    return draft
