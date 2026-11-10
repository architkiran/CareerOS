"""Expiring display signals derived from source statements and reviewed evidence.

This is not a candidate work-authorization answer. The matching gate remains separate.
"""

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import case, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import Case

from careeros.common.clock import utcnow
from careeros.db.models import Evidence, Job, JobSourceRecord, Source
from careeros.modules.matching.filters import authorization_claims
from careeros.modules.research.service import _reference_time, summarize_policy
from careeros.modules.sources.text import safe_posting_url

LABELS = {
    "confirmed": "Confirmed",
    "not_supported": "Not supported",
    "uncertain": "Uncertain",
    "not_indicated": "Not indicated",
}
OFFICIAL = {"greenhouse", "lever", "ashby", "smartrecruiters"}


def effective_state(job: Job, now: datetime | None = None) -> str:
    now = now or utcnow()
    if job.sponsorship_checked_at is None:
        return "uncertain"
    if job.sponsorship_valid_until and job.sponsorship_valid_until < now:
        return "uncertain"
    return job.sponsorship_status if job.sponsorship_status in LABELS else "uncertain"


def state_expression() -> Case[str]:
    return case((Job.sponsorship_valid_until < utcnow(), "uncertain"), else_=Job.sponsorship_status)


def refresh_signals(session: Session, jobs: list[Job]) -> None:
    """Batch load provenance; no AI or network work during matching or inbox reads."""
    if not jobs:
        return
    evidence: dict[str, list[Evidence]] = defaultdict(list)
    for ev in session.scalars(
        select(Evidence).where(Evidence.company_id.in_({j.company_id for j in jobs}))
    ):
        evidence[ev.company_id].append(ev)
    sightings: dict[str, list[tuple[JobSourceRecord, str]]] = defaultdict(list)
    for record, kind in session.execute(
        select(JobSourceRecord, Source.source_type)
        .join(Source, Source.id == JobSourceRecord.source_id)
        .where(JobSourceRecord.job_id.in_([j.id for j in jobs]))
    ):
        sightings[record.job_id].append((record, kind))
    now = utcnow()
    for job in jobs:
        scoped = [e for e in evidence[job.company_id] if e.job_id is None or e.job_id == job.id]
        policy = summarize_policy(scoped, job.id)
        state, facts, expiry = "not_indicated", [], None
        sources = sorted(
            sightings[job.id],
            key=lambda pair: (
                pair[1] not in OFFICIAL,
                pair[0].is_listed is False,
                -pair[0].last_seen_at.timestamp(),
            ),
        )
        claims = authorization_claims(job.description_text)
        role_basis = any(e.job_id == job.id for e in policy.basis)
        direct_statement = bool(
            claims
            and sources
            and sources[0][1] in OFFICIAL
            and sources[0][0].is_listed is not False
        )
        if policy.basis and (role_basis or not direct_statement):
            facts = [
                {
                    "url": e.source_url,
                    "quote": e.short_excerpt or e.claim_text,
                    "observed_at": e.retrieved_at.isoformat(),
                    "evidence_id": e.id,
                    "kind": e.source_kind,
                }
                for e in policy.basis
            ]
            expiry = min(_reference_time(e) + timedelta(days=180) for e in policy.basis)
            if policy.conflict or policy.stale:
                state = "uncertain"
            elif policy.status == "no_sponsorship":
                state = "not_supported"
            elif policy.status == "sponsorship_offered":
                state = (
                    "confirmed" if any(e.job_id == job.id for e in policy.basis) else "uncertain"
                )
            else:
                state = "uncertain"
        else:
            if claims and sources:
                record, kind = sources[0]
                facts = [
                    {
                        "url": record.source_url,
                        "quote": quote,
                        "observed_at": record.last_seen_at.isoformat(),
                        "source_record_id": record.id,
                        "kind": kind,
                    }
                    for _, quote in claims
                ]
                expiry = record.last_seen_at + timedelta(days=30)
                if (
                    kind not in OFFICIAL
                    or record.is_listed is False
                    or expiry < now
                    or safe_posting_url(record.source_url) is None
                ):
                    state = "uncertain"
                elif any(c == "no_sponsorship" for c, _ in claims):
                    state = "not_supported"
                elif any(c == "sponsorship_offered" for c, _ in claims):
                    state = "confirmed"
                else:
                    state = "uncertain"
            elif any(e.reviewer_status != "rejected" for e in scoped):
                state = "uncertain"  # Pending/rejected/third-party items cannot confirm policy.
                facts = [
                    {
                        "url": e.source_url,
                        "quote": e.short_excerpt or e.claim_text,
                        "observed_at": e.retrieved_at.isoformat(),
                        "evidence_id": e.id,
                        "kind": e.source_kind,
                    }
                    for e in scoped
                    if e.reviewer_status != "rejected"
                ][:3]
        job.sponsorship_status = state
        job.sponsorship_evidence_json = facts
        job.sponsorship_checked_at = now
        job.sponsorship_valid_until = expiry
