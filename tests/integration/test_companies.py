from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import Company, Evidence, ResearchItem
from careeros.modules.companies import service
from careeros.modules.research import service as research
from careeros.modules.system.settings_store import set_setting
from tests.conftest import post_form


def seed(session: Session) -> Company:
    set_setting(
        session,
        "career.preferences",
        {"target_companies": ["Example Financial", "Second Employer"]},
    )
    assert service.ensure_watchlist(session) == 2
    session.commit()
    assert service.ensure_watchlist(session) == 0
    session.commit()
    return session.scalars(
        select(Company).where(Company.canonical_name == "Example Financial")
    ).one()


def test_watchlist_and_company_workspace_are_honest(session: Session, client: TestClient) -> None:
    company = seed(session)
    assert client.get("/companies").status_code == 200
    page = client.get("/companies/" + company.id)
    assert page.status_code == 200 and "Unknown" in page.text
    assert "No configured feed" in page.text and "No sourced facts captured" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert len(session.scalars(select(ResearchItem)).all()) == 2
    assert client.get("/companies/missing").status_code == 404
    assert client.post("/companies/watchlist").status_code == 403


def test_company_evidence_is_pending_and_third_party_does_not_set_policy(
    session: Session,
    client: TestClient,
) -> None:
    company = seed(session)
    url = f"/companies/{company.id}/evidence"
    assert client.post(url).status_code == 403
    assert (
        post_form(
            client,
            url,
            {
                "claim_type": "sponsorship_offered",
                "claim_text": "A third-party claim",
                "source_kind": "third_party",
                "source_url": "https://example.org/source",
            },
        ).status_code
        == 303
    )
    session.expire_all()
    evidence = session.scalars(select(Evidence)).one()
    assert evidence.reviewer_status == "pending"
    assert (
        post_form(
            client,
            f"/companies/{company.id}/evidence/{evidence.id}/review",
            {"decision": "accepted"},
        ).status_code
        == 303
    )
    session.expire_all()
    assert research.employer_policy(session, company.id).status == "unknown"
    assert (
        post_form(
            client,
            url,
            {
                "claim_type": "other",
                "claim_text": "<script>unsafe()</script>",
                "source_kind": "official_company",
                "source_url": "https://example.org/about",
            },
        ).status_code
        == 303
    )
    page = client.get("/companies/" + company.id).text
    assert "<script>unsafe()" not in page and "&lt;script&gt;unsafe()" in page


def test_old_source_date_cannot_be_refreshed_into_current_policy(session: Session) -> None:
    company = seed(session)
    item = service.open_company_research(session, company.id)
    evidence = research.add_evidence(
        session,
        item.id,
        research.EvidenceIn(
            claim_type="sponsorship_offered",
            claim_text="Historical policy in an old report",
            source_kind="official_company",
            source_url="https://example.org/old-report",
            source_date=(utcnow() - timedelta(days=365)).date(),
            confidence="high",
            checked=True,
        ),
    )
    session.commit()
    policy = research.employer_policy(session, company.id)
    assert policy.status == "unknown" and policy.stale
    assert research.evidence_age_days(evidence) >= 365


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "https://", "https://user:secret@example.org/"]
)
def test_invalid_evidence_urls_are_rejected(session: Session, client: TestClient, url: str) -> None:
    company = seed(session)
    assert (
        post_form(
            client,
            f"/companies/{company.id}/evidence",
            {
                "claim_type": "other",
                "claim_text": "Claim",
                "source_kind": "official_company",
                "source_url": url,
            },
        ).status_code
        == 422
    )


def test_research_agent_leads_cannot_self_accept(session: Session) -> None:
    company = seed(session)
    data = research.EvidenceIn(
        claim_type="sponsorship_offered",
        claim_text="Draft claim for review",
        source_kind="official_company",
        source_url="https://example.org/policy",
        checked=True,
    )
    evidence = service.add_research_lead(session, company.id, data)
    session.commit()
    assert evidence.reviewer_status == "pending" and evidence.origin == "research"
    assert research.employer_policy(session, company.id).status == "unknown"
    assert service.add_research_lead(session, company.id, data).id == evidence.id
