from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import Evidence, Job
from careeros.modules.ingestion.service import upsert_job
from careeros.modules.jobs.service import JobFilters, list_jobs
from careeros.modules.jobs.sponsorship import effective_state, refresh_signals
from careeros.modules.sources.registry import SourceIn, add_source
from tests.integration.test_discovery_integrity import payload


def setup_role(
    session: Session, description: str = "SQL reporting", kind: str = "greenhouse"
) -> Job:
    source = add_source(
        session,
        SourceIn(type=kind, token="public" if kind == "remotive" else "example", name="Example"),
    )  # type: ignore[arg-type]
    job, _ = upsert_job(session, source, payload(description_text=description), utcnow())
    session.flush()
    return job


def evidence(
    session: Session, job: Job, claim: str, *, scoped: bool = True, **kw: object
) -> Evidence:
    ev = Evidence(
        company_id=job.company_id,
        job_id=job.id if scoped else None,
        claim_type=claim,
        claim_text="A reviewed source statement",
        source_kind="official_posting" if scoped else "official_company",
        source_url="https://employer.example/policy",
        confidence="high",
        origin="user",
        reviewer_status="accepted",
        **kw,
    )
    session.add(ev)
    session.flush()
    return ev


@pytest.mark.parametrize(
    "description,state",
    [
        ("SQL reporting. Nothing about immigration.", "not_indicated"),
        ("Visa sponsorship is available for this role.", "confirmed"),
        ("We do not sponsor visas for this role.", "not_supported"),
    ],
)
def test_official_posting_four_state_labels(session: Session, description: str, state: str) -> None:
    job = setup_role(session, description)
    refresh_signals(session, [job])
    assert effective_state(job) == state
    if state != "not_indicated":
        assert job.sponsorship_evidence_json[0]["source_record_id"]


def test_third_party_claim_is_a_lead_not_confirmation(session: Session) -> None:
    job = setup_role(session, "Visa sponsorship is available.", kind="remotive")
    refresh_signals(session, [job])
    assert effective_state(job) == "uncertain"


def test_role_policy_beats_company_policy_and_keeps_evidence(session: Session) -> None:
    job = setup_role(session)
    evidence(session, job, "no_sponsorship", scoped=False)
    role = evidence(session, job, "sponsorship_offered")
    refresh_signals(session, [job])
    assert effective_state(job) == "confirmed"
    assert job.sponsorship_evidence_json[0]["evidence_id"] == role.id


def test_current_official_role_statement_beats_generic_company_policy(session: Session) -> None:
    job = setup_role(session, "Visa sponsorship is available for this role.")
    evidence(session, job, "no_sponsorship", scoped=False)
    refresh_signals(session, [job])
    assert effective_state(job) == "confirmed"


def test_company_only_positive_policy_is_not_role_confirmation(session: Session) -> None:
    job = setup_role(session)
    evidence(session, job, "sponsorship_offered", scoped=False)
    refresh_signals(session, [job])
    assert effective_state(job) == "uncertain"


def test_conflicting_or_old_evidence_is_uncertain(session: Session) -> None:
    job = setup_role(session)
    old = evidence(session, job, "sponsorship_offered", retrieved_at=utcnow() - timedelta(days=200))
    refresh_signals(session, [job])
    assert effective_state(job) == "uncertain"
    old.retrieved_at = utcnow()
    evidence(session, job, "no_sponsorship")
    refresh_signals(session, [job])
    assert effective_state(job) == "uncertain"


def test_rejected_and_other_job_evidence_never_confirm(session: Session) -> None:
    job = setup_role(session)
    ev = evidence(session, job, "sponsorship_offered")
    ev.reviewer_status = "rejected"
    refresh_signals(session, [job])
    assert effective_state(job) == "not_indicated"


def test_expired_cache_cannot_pass_confirmed_sql_filter(session: Session) -> None:
    job = setup_role(session, "Visa sponsorship is available.")
    refresh_signals(session, [job])
    job.sponsorship_valid_until = utcnow() - timedelta(days=1)
    session.flush()
    assert effective_state(job) == "uncertain"
    assert list_jobs(session, JobFilters(sponsorship="confirmed"))[1] == 0
    assert list_jobs(session, JobFilters(sponsorship="uncertain"))[1] == 1
