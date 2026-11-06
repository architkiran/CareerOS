from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from careeros.common.clock import utcnow
from careeros.db.models import Company, Evidence, Job, JobSourceRecord, ResearchItem, Source, Task
from careeros.modules.jobs import service as jobs
from careeros.modules.matching import service as matching
from careeros.modules.profile import service as profile_service
from careeros.modules.profile.schemas import WorkAuthorizationIn
from careeros.modules.research import service as research
from tests.conftest import post_form

URL = "https://acme.example/careers/policy"


@pytest.fixture
def factory(app: FastAPI) -> sessionmaker[Session]:
    return app.state.session_factory  # type: ignore[no-any-return]


def _job(
    f: sessionmaker[Session],
    title: str = "Data Analyst",
    desc: str = "SQL and Python.",
    company: str = "Acme",
) -> str:
    with f() as s:
        c = s.scalars(select(Company).where(Company.normalized_name == company.lower())).first()
        if c is None:
            c = Company(canonical_name=company, normalized_name=company.lower())
            s.add(c)
            s.flush()
        src = s.scalars(select(Source)).first()
        if src is None:
            src = Source(source_type="greenhouse", board_token="acme", display_name="Acme")
            s.add(src)
            s.flush()
        j = Job(
            canonical_url=f"https://acme.example/jobs/{title}",
            company_id=c.id,
            title=title,
            normalized_title=title.lower(),
            description_text=desc,
            description_hash="h",
            dedupe_key=title,
            employment_type="full_time",
            location_text="Boston, MA",
        )
        s.add(j)
        s.flush()
        s.add(
            JobSourceRecord(
                job_id=j.id,
                source_id=src.id,
                external_id=title,
                source_url=f"https://boards.example/acme/{title}",
                raw_json={},
                raw_hash="r",
            )
        )
        s.commit()
        return j.id


def _ev(**kw: object) -> research.EvidenceIn:
    base: dict[str, object] = dict(
        claim_type="sponsorship_offered",
        claim_text="We sponsor H-1B",
        source_kind="official_company",
        source_url=URL,
        checked=True,
    )
    return research.EvidenceIn(**(base | kw))  # type: ignore[arg-type]


def test_open_research_extracts_posting_statements(factory: sessionmaker[Session]) -> None:
    jid = _job(factory, desc="Great role. We are unable to provide visa sponsorship. Apply now.")
    with factory() as s:
        item = research.open_research(s, jid)
        again = research.open_research(s, jid)
        s.commit()
        assert item.id == again.id  # idempotent
        [ev] = s.scalars(select(Evidence)).all()
        assert ev.claim_type == "no_sponsorship" and ev.origin == "job_posting"
        assert ev.reviewer_status == "pending" and "unable to provide visa sponsorship" in (
            ev.short_excerpt or ""
        )
        assert ev.source_url == "https://boards.example/acme/Data Analyst"
        # pending evidence never decides policy
        assert research.employer_policy(s, ev.company_id, jid).status == "unknown"


def test_silent_posting_creates_no_evidence(factory: sessionmaker[Session]) -> None:
    jid = _job(factory)
    with factory() as s:
        item = research.open_research(s, jid)
        assert s.scalars(select(Evidence)).all() == []
        assert "says nothing about sponsorship" in (item.summary or "")


def test_shortlisting_opens_research(factory: sessionmaker[Session]) -> None:
    jid = _job(factory)
    with factory() as s:
        jobs.triage(s, jid, "shortlist")
        s.commit()
        assert research.research_for_job(s, jid) is not None
        jobs.triage(s, jid, "save")
        assert len(s.scalars(select(ResearchItem)).all()) == 1


def test_accepted_official_evidence_sets_policy(factory: sessionmaker[Session]) -> None:
    jid = _job(factory)
    with factory() as s:
        item = research.open_research(s, jid)
        research.add_evidence(s, item.id, _ev(confidence="high"))
        p = research.employer_policy(s, item.company_id, jid)
        assert (p.status, p.confidence, p.label) == (
            "sponsorship_offered",
            "high",
            "Sponsorship offered",
        )
        assert item.status == "in_progress"


def test_third_party_is_only_a_lead(factory: sessionmaker[Session]) -> None:
    jid = _job(factory)
    with factory() as s:
        item = research.open_research(s, jid)
        research.add_evidence(s, item.id, _ev(source_kind="third_party"))
        p = research.employer_policy(s, item.company_id, jid)
        assert p.status == "unknown" and len(p.leads) == 1


def test_unchecked_evidence_is_pending(factory: sessionmaker[Session]) -> None:
    jid = _job(factory)
    with factory() as s:
        item = research.open_research(s, jid)
        ev = research.add_evidence(s, item.id, _ev(checked=False))
        assert ev.reviewer_status == "pending"
        assert research.employer_policy(s, item.company_id, jid).status == "unknown"
        research.review_evidence(s, ev.id, "accepted")
        assert research.employer_policy(s, item.company_id, jid).status == "sponsorship_offered"
        research.review_evidence(s, ev.id, "rejected")
        assert research.employer_policy(s, item.company_id, jid).status == "unknown"


def test_conflict_stays_unknown(factory: sessionmaker[Session]) -> None:
    jid = _job(factory)
    with factory() as s:
        item = research.open_research(s, jid)
        research.add_evidence(s, item.id, _ev())
        research.add_evidence(s, item.id, _ev(claim_type="no_sponsorship", claim_text="No"))
        p = research.employer_policy(s, item.company_id, jid)
        assert p.status == "unknown" and p.conflict


def test_job_specific_evidence_beats_company_wide(factory: sessionmaker[Session]) -> None:
    jid = _job(factory, desc="We will not sponsor visas for this role.")
    with factory() as s:
        item = research.open_research(s, jid)
        research.add_evidence(s, item.id, _ev())  # company says they sponsor in general
        posting = s.scalars(select(Evidence).where(Evidence.origin == "job_posting")).one()
        research.review_evidence(s, posting.id, "accepted")
        assert research.employer_policy(s, item.company_id, jid).status == "no_sponsorship"


def test_other_jobs_evidence_does_not_apply(factory: sessionmaker[Session]) -> None:
    a = _job(factory, "Analyst A", "We do not sponsor visas.")
    b = _job(factory, "Analyst B")
    with factory() as s:
        item = research.open_research(s, a)
        ev = s.scalars(select(Evidence)).one()
        research.review_evidence(s, ev.id, "accepted")
        assert research.employer_policy(s, item.company_id, a).status == "no_sponsorship"
        assert research.employer_policy(s, item.company_id, b).status == "unknown"


def test_stale_evidence_cannot_establish_current_policy(factory: sessionmaker[Session]) -> None:
    jid = _job(factory)
    with factory() as s:
        item = research.open_research(s, jid)
        ev = research.add_evidence(s, item.id, _ev(confidence="high"))
        ev.retrieved_at = utcnow() - timedelta(days=400)
        p = research.employer_policy(s, item.company_id, jid)
        assert p.stale and p.confidence == "low" and p.status == "unknown"


def test_citizenship_flag(factory: sessionmaker[Session]) -> None:
    jid = _job(factory)
    with factory() as s:
        item = research.open_research(s, jid)
        research.add_evidence(s, item.id, _ev(claim_type="citizenship_required", claim_text="ITAR"))
        p = research.employer_policy(s, item.company_id, jid)
        assert p.citizenship_required and p.status == "unknown"


@pytest.mark.parametrize(
    ("kw", "msg"),
    [
        ({"source_url": "ftp://x"}, "http"),
        ({"claim_text": ""}, "at least 1"),
        ({"source_date": (utcnow() + timedelta(days=5)).date()}, "future"),
        ({"claim_type": "rumour"}, "claim_type"),
        ({"source_kind": "blog"}, "source_kind"),
    ],
)
def test_evidence_validation(kw: dict, msg: str) -> None:  # type: ignore[type-arg]
    with pytest.raises(ValueError, match=msg):
        _ev(**kw)


def test_policy_feeds_matching(factory: sessionmaker[Session]) -> None:
    jid = _job(factory)
    with factory() as s:
        profile_service.add_default_lanes(s)
        profile_service.save_work_authorization(
            s, WorkAuthorizationIn(requires_sponsorship_now="yes", confirmed=True)
        )
        s.commit()
        matching.score_jobs(s)
        s.commit()

        def wa() -> str:
            view = next(
                v for v in matching.matches_for_job(s, jid) if v.lane_name == "Data / BI Analyst"
            )
            return next(
                f["decision"]
                for f in view.match.hard_filter_results_json
                if f["name"] == "work_authorization"
            )

        assert wa() == "unknown"
        item = research.open_research(s, jid)
        ev = research.add_evidence(s, item.id, _ev(claim_type="no_sponsorship", claim_text="No"))
        s.commit()
        matching.score_jobs(s)
        s.commit()
        assert wa() == "fail"
        research.review_evidence(s, ev.id, "rejected")
        research.add_evidence(s, item.id, _ev())
        s.commit()
        matching.score_jobs(s)
        s.commit()
        assert wa() == "pass"


def test_complete_and_reopen(factory: sessionmaker[Session]) -> None:
    jid = _job(factory)
    with factory() as s:
        item = research.open_research(s, jid)
        research.complete_research(s, item.id, "Checked careers page; nothing stated.")
        assert item.status == "done" and item.reviewed_at and "careers page" in (item.summary or "")
        research.reopen_research(s, item.id)
        assert item.status == "in_progress" and item.reviewed_at is None
        with pytest.raises(LookupError):
            research.complete_research(s, "missing", None)


# ---------- web ----------


def test_research_page_states(factory: sessionmaker[Session], client: TestClient) -> None:
    assert 'data-testid="research-empty"' in client.get("/research").text
    jid = _job(factory)
    post_form(client, f"/jobs/{jid}/triage", {"action": "shortlist"})
    html = client.get("/research").text
    assert html.count('data-testid="research-row"') == 1 and "Unknown" in html
    assert 'data-testid="research-empty"' in client.get("/research?status=done").text


def test_job_page_evidence_flow(factory: sessionmaker[Session], client: TestClient) -> None:
    jid = _job(factory)
    page = client.get(f"/jobs/{jid}").text
    assert "Start research" in page and 'data-testid="policy-status">Unknown<' in page
    assert post_form(client, f"/jobs/{jid}/research").status_code == 303
    with factory() as s:
        item_id = research.research_for_job(s, jid).id  # type: ignore[union-attr]
    bad = post_form(
        client,
        f"/research/{item_id}/evidence",
        {
            "claim_type": "sponsorship_offered",
            "claim_text": "x",
            "source_kind": "official_company",
            "source_url": "javascript:alert(1)",
        },
    )
    assert bad.status_code == 422 and "http" in bad.text
    ok = post_form(
        client,
        f"/research/{item_id}/evidence",
        {
            "claim_type": "sponsorship_offered",
            "claim_text": "Careers FAQ says they sponsor",
            "source_kind": "official_company",
            "source_url": URL,
            "confidence": "high",
            "checked": "on",
            "short_excerpt": "<b>We sponsor</b>",
        },
    )
    assert ok.status_code == 303
    page = client.get(f"/jobs/{jid}").text
    assert 'data-testid="policy-status">Sponsorship offered<' in page
    assert "&lt;b&gt;We sponsor" in page and "<b>We sponsor" not in page
    with factory() as s:
        ev = s.scalars(select(Evidence)).one()
        assert [t.task_type for t in s.scalars(select(Task))] == ["match.all"]
    post_form(client, f"/evidence/{ev.id}/review", {"decision": "rejected"})
    assert 'data-testid="policy-status">Unknown<' in client.get(f"/jobs/{jid}").text
    assert post_form(client, f"/evidence/{ev.id}/review", {"decision": "maybe"}).status_code == 422
    assert (
        post_form(client, "/evidence/missing/review", {"decision": "accepted"}).status_code == 404
    )
    post_form(client, f"/research/{item_id}/complete", {"summary": "done"})
    assert 'data-testid="research-status">done<' in client.get(f"/jobs/{jid}").text
    assert post_form(client, "/jobs/missing/research").status_code == 404
