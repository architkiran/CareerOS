"""Employer research: evidence capture, review, and the resulting policy summary.

Rules (docs/PRODUCT_SPEC.md, "Work authorization intelligence"):
- unknown is a valid, visible state;
- only accepted evidence from official postings, official company pages or
  government data can set a policy; third-party sources are leads only;
- job-specific evidence beats company-wide evidence;
- conflicting accepted evidence leaves the policy unknown and says so;
- "they sponsored someone before" is never proof for a specific job.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import Company, Evidence, Job, JobSourceRecord, ResearchItem
from careeros.modules.events.service import record_event
from careeros.modules.matching.filters import authorization_claims

ClaimType = Literal[
    "sponsorship_offered", "no_sponsorship", "case_by_case", "citizenship_required", "other"
]
SourceKind = Literal["official_posting", "official_company", "government", "third_party"]
Confidence = Literal["high", "medium", "low"]
Policy = Literal["sponsorship_offered", "no_sponsorship", "case_by_case", "unknown"]

CLAIM_LABELS = {
    "sponsorship_offered": "Sponsors visas",
    "no_sponsorship": "Does not sponsor",
    "case_by_case": "Case by case",
    "citizenship_required": "Citizenship or clearance required",
    "other": "Other",
}
POLICY_LABELS = {
    "sponsorship_offered": "Sponsorship offered",
    "no_sponsorship": "No sponsorship",
    "case_by_case": "Case by case",
    "unknown": "Unknown",
}
AUTHORITATIVE = {"official_posting", "official_company", "government"}
STALE_AFTER = timedelta(days=180)
_POLICY_CLAIMS = {"sponsorship_offered", "no_sponsorship", "case_by_case"}


class EvidenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_type: ClaimType
    claim_text: str = Field(min_length=1, max_length=1000)
    source_kind: SourceKind
    source_url: str = Field(min_length=1, max_length=1000)
    source_title: str | None = Field(default=None, max_length=300)
    source_date: date | None = None
    short_excerpt: str | None = Field(default=None, max_length=600)
    confidence: Confidence = "medium"
    checked: bool = False  # "I opened this source and it says this"

    @field_validator("source_url")
    @classmethod
    def _http(cls, v: str) -> str:
        parsed = urlsplit(v)
        if (
            parsed.scheme not in ("https", "http")
            or not parsed.hostname
            or parsed.username is not None
        ):
            raise ValueError("Source URL must use HTTP(S), name a host and omit credentials.")
        return v

    @field_validator("source_date")
    @classmethod
    def _not_future(cls, v: date | None) -> date | None:
        if v is not None and v > utcnow().date():
            raise ValueError("Source date can't be in the future.")
        return v


class ResearchError(ValueError):
    pass


def _job_source_url(session: Session, job_id: str) -> str | None:
    stmt = (
        select(JobSourceRecord.source_url)
        .where(JobSourceRecord.job_id == job_id)
        .order_by(JobSourceRecord.first_seen_at)
    )
    return session.scalars(stmt).first()


def open_research(session: Session, job_id: str) -> ResearchItem:
    """Start (or return) sponsorship research for a job, extracting posting statements."""
    job = session.get(Job, job_id)
    if job is None:
        raise LookupError("Job not found")
    item = session.scalars(
        select(ResearchItem).where(
            ResearchItem.job_id == job_id, ResearchItem.research_type == "sponsorship"
        )
    ).first()
    if item is not None:
        return item
    item = ResearchItem(company_id=job.company_id, job_id=job.id, research_type="sponsorship")
    session.add(item)
    session.flush()
    url = _job_source_url(session, job.id) or job.canonical_url
    claims = authorization_claims(job.description_text)
    for claim, quote in claims:
        session.add(
            Evidence(
                research_item_id=item.id,
                company_id=job.company_id,
                job_id=job.id,
                claim_type=claim,
                claim_text=f"Job posting: {CLAIM_LABELS[claim].lower()}",
                source_kind="official_posting",
                source_url=url,
                source_title=job.title,
                confidence="high",
                short_excerpt=quote,
                origin="job_posting",
                reviewer_status="pending",
            )
        )
    item.summary = (
        f"Found {len(claims)} statement(s) in the posting; review them."
        if claims
        else "The posting says nothing about sponsorship. "
        "Check the company's careers or immigration page."
    )
    record_event(
        session,
        "research.started",
        f"Research started: {job.title}",
        entity_type="job",
        entity_id=job.id,
        metadata={"claims_found": len(claims)},
    )
    return item


def add_evidence(session: Session, item_id: str, data: EvidenceIn) -> Evidence:
    item = session.get(ResearchItem, item_id)
    if item is None:
        raise LookupError("Research item not found")
    ev = Evidence(
        research_item_id=item.id,
        company_id=item.company_id,
        job_id=item.job_id if data.source_kind == "official_posting" else None,
        claim_type=data.claim_type,
        claim_text=data.claim_text,
        source_kind=data.source_kind,
        source_url=data.source_url,
        source_title=data.source_title,
        source_date=data.source_date,
        confidence=data.confidence,
        short_excerpt=data.short_excerpt,
        origin="user",
        reviewer_status="accepted" if data.checked else "pending",
        reviewed_at=utcnow() if data.checked else None,
    )
    session.add(ev)
    if item.status == "open":
        item.status = "in_progress"
    session.flush()
    record_event(
        session,
        "research.evidence_added",
        f"Evidence added: {CLAIM_LABELS[data.claim_type]} ({data.source_kind.replace('_', ' ')})",
        entity_type="evidence",
        entity_id=ev.id,
    )
    return ev


def review_evidence(
    session: Session, evidence_id: str, decision: Literal["accepted", "rejected", "pending"]
) -> Evidence:
    ev = session.get(Evidence, evidence_id)
    if ev is None:
        raise LookupError("Evidence not found")
    if decision not in ("accepted", "rejected", "pending"):
        raise ResearchError("Unknown review decision")
    ev.reviewer_status = decision
    ev.reviewed_at = utcnow() if decision != "pending" else None
    record_event(
        session,
        "research.evidence_reviewed",
        f"Evidence {decision}: {CLAIM_LABELS.get(ev.claim_type, ev.claim_type)}",
        entity_type="evidence",
        entity_id=ev.id,
    )
    return ev


def complete_research(session: Session, item_id: str, summary: str | None) -> ResearchItem:
    item = session.get(ResearchItem, item_id)
    if item is None:
        raise LookupError("Research item not found")
    policy = employer_policy(session, item.company_id, item.job_id)
    item.status = "done"
    item.summary = (summary or "").strip()[:2000] or item.summary
    item.confidence = policy.confidence
    item.reviewed_at = utcnow()
    record_event(
        session,
        "research.completed",
        f"Research done: {POLICY_LABELS[policy.status]}",
        entity_type="research_item",
        entity_id=item.id,
    )
    return item


def reopen_research(session: Session, item_id: str) -> ResearchItem:
    item = session.get(ResearchItem, item_id)
    if item is None:
        raise LookupError("Research item not found")
    item.status = "in_progress"
    item.reviewed_at = None
    return item


# ---------- policy ----------


@dataclass
class PolicySummary:
    status: Policy
    confidence: str | None
    basis: list[Evidence] = field(default_factory=list)
    leads: list[Evidence] = field(default_factory=list)
    conflict: bool = False
    stale: bool = False
    citizenship_required: bool = False

    @property
    def label(self) -> str:
        return POLICY_LABELS[self.status]

    @property
    def note(self) -> str | None:
        if not self.basis:
            return None
        ev = self.basis[0]
        return f"{ev.claim_text} ({ev.source_url})"


def _reference_time(ev: Evidence) -> datetime:
    published = (
        datetime.combine(ev.source_date, datetime.min.time(), tzinfo=UTC)
        if ev.source_date
        else ev.retrieved_at
    )
    return min(published, ev.retrieved_at)


def _is_stale(ev: Evidence, now: datetime) -> bool:
    return now - _reference_time(ev) > STALE_AFTER


def employer_policy(session: Session, company_id: str, job_id: str | None = None) -> PolicySummary:
    rows = list(
        session.scalars(
            select(Evidence)
            .where(
                Evidence.company_id == company_id,
                Evidence.reviewer_status == "accepted",
            )
            .order_by(Evidence.retrieved_at.desc())
        )
    )
    # Job-specific evidence for *other* jobs says nothing about this one.
    rows = [e for e in rows if e.job_id is None or e.job_id == job_id]
    authoritative = [e for e in rows if e.source_kind in AUTHORITATIVE]
    leads = [e for e in rows if e.source_kind not in AUTHORITATIVE]
    now = utcnow()
    citizenship = any(
        e.claim_type == "citizenship_required" and not _is_stale(e, now) for e in authoritative
    )
    scoped = [e for e in authoritative if e.job_id == job_id and e.claim_type in _POLICY_CLAIMS]
    if not scoped:
        scoped = [e for e in authoritative if e.job_id is None and e.claim_type in _POLICY_CLAIMS]
    now = utcnow()
    if not scoped:
        return PolicySummary("unknown", None, [], leads, citizenship_required=citizenship)
    claims = {e.claim_type for e in scoped}
    if len(claims) > 1:
        return PolicySummary(
            "unknown", "low", scoped, leads, conflict=True, citizenship_required=citizenship
        )
    status: Policy = scoped[0].claim_type  # type: ignore[assignment]
    rank = {"high": 3, "medium": 2, "low": 1}
    confidence = max((e.confidence for e in scoped), key=lambda c: rank.get(c, 0))
    stale = all(_is_stale(e, now) for e in scoped)
    if stale:
        return PolicySummary(
            "unknown", "low", scoped, leads, stale=True, citizenship_required=citizenship
        )
    return PolicySummary(
        status, confidence, scoped, leads, stale=False, citizenship_required=citizenship
    )


def evidence_for(session: Session, company_id: str, job_id: str | None) -> list[Evidence]:
    rows = session.scalars(
        select(Evidence)
        .where(Evidence.company_id == company_id)
        .order_by(Evidence.retrieved_at.desc())
    )
    return [e for e in rows if e.job_id is None or e.job_id == job_id]


def research_for_job(session: Session, job_id: str) -> ResearchItem | None:
    return session.scalars(select(ResearchItem).where(ResearchItem.job_id == job_id)).first()


@dataclass
class QueueRow:
    item: ResearchItem
    job: Job | None
    company: Company
    policy: PolicySummary
    pending: int


def research_queue(session: Session, status: str | None = None) -> list[QueueRow]:
    stmt = select(ResearchItem).order_by(ResearchItem.created_at.desc())
    if status:
        stmt = stmt.where(ResearchItem.status == status)
    out = []
    for item in session.scalars(stmt):
        company = session.get(Company, item.company_id)
        assert company is not None
        job = session.get(Job, item.job_id) if item.job_id else None
        pending = sum(
            1
            for e in evidence_for(session, item.company_id, item.job_id)
            if e.reviewer_status == "pending"
        )
        out.append(
            QueueRow(item, job, company, employer_policy(session, company.id, item.job_id), pending)
        )
    return out


def evidence_age_days(ev: Evidence) -> int:
    return max(0, (utcnow() - _reference_time(ev)).days)
