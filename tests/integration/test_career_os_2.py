"""End-to-end: ingest → verdicts → digest → Today page, with LCA evidence."""

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from careeros.db.models import (
    CandidateProfile,
    Job,
    JobSourceRecord,
    JobVerdict,
    Source,
    WorkAuthorizationProfile,
)
from careeros.modules.eligibility import service as eligibility
from careeros.modules.ingestion.service import run_source
from careeros.modules.sources.registry import SourceIn, add_source
from careeros.modules.sponsorship import lca

NOW = datetime.now(UTC)
LISTING = {
    "id": "abc",
    "title": "Data Analyst",
    "company_name": "Acme Financial",
    "active": True,
    "is_visible": True,
    "date_posted": int(NOW.timestamp()) - 7200,
    "locations": ["Boston, MA"],
    "url": "https://boards.greenhouse.io/acmefinancial/jobs/123",
    "sponsorship": "Other",
}
GH_JOB = {
    "id": 123,
    "title": "Data Analyst",
    "absolute_url": "https://boards.greenhouse.io/acmefinancial/jobs/123",
    "location": {"name": "Boston, MA"},
    "updated_at": "2026-11-10T10:00:00Z",
    "first_published": "2026-11-09T10:00:00Z",
    "content": "<p>Full-time role for recent graduates. 0-1 years of experience. SQL.</p>",
}


class Feeds:
    def __init__(self):
        self.gh = [deepcopy(GH_JOB)]

    def get_json(self, url, **kwargs):
        if "raw.githubusercontent.com" in url:
            return [deepcopy(LISTING)], 200
        return {"jobs": deepcopy(self.gh), "meta": {"total": len(self.gh)}}, 200


def _profile(session, confirmed=True):
    profile = CandidateProfile(
        display_name="Test Candidate", relocation_preferences_json={"open_to_relocation": True}
    )
    session.add(profile)
    session.flush()
    session.add(
        WorkAuthorizationProfile(
            profile_id=profile.id,
            status_text="F-1",
            requires_sponsorship_now="no",
            requires_sponsorship_future="yes",
            verified_at=NOW if confirmed else None,
        )
    )
    session.commit()


def _source(session, kind, token, name):
    source = add_source(session, SourceIn(type=kind, token=token, name=name))
    session.commit()
    return source


def _lca_csv(tmp_path: Path) -> Path:
    path = tmp_path / "LCA_FY2026.csv"
    path.write_text(
        "CASE_STATUS,EMPLOYER_NAME,JOB_TITLE,SOC_TITLE,WORKSITE_STATE,DECISION_DATE,"
        "NEW_EMPLOYMENT\n"
        'Certified,"Acme Financial, Inc.",Data Analyst,Data Scientists,MA,2026-03-01,1\n'
        "Certified,ACME FINANCIAL INC,Software Engineer,Software Developers,MA,2026-04-01,1\n"
        "Denied,ACME FINANCIAL INC,Data Analyst,Data Scientists,MA,2026-04-02,1\n"
        "Certified - Withdrawn,Other Bank and Trust LLC,Analyst,Financial Analysts,NY,"
        "2026-02-01,0\n"
    )
    return path


def test_community_stub_is_verified_by_official_source_and_reaches_level_b(
    session, client, tmp_path
):
    _profile(session)
    feeds = Feeds()
    community = _source(session, "community", "simplify-newgrad", "New-grad list")
    assert run_source(session, community, feeds).new == 1
    eligibility.evaluate_all(session)
    session.commit()
    stub = session.scalars(select(JobVerdict)).one()
    # Third-party only, no posting text: unverified, never eligible.
    assert (stub.verdict, stub.sponsorship_level) == ("research", "U")
    stage = next(c for c in stub.checks_json if c["key"] == "stage")
    assert stage["decision"] == "assumed"

    official = _source(session, "greenhouse", "acmefinancial", "Acme Financial")
    assert run_source(session, official, feeds).duplicates == 1
    job = session.scalars(select(Job)).one()  # merged, not duplicated
    assert "recent graduates" in job.description_text
    assert len(session.scalars(select(JobSourceRecord)).all()) == 2

    assert lca.import_file(session, _lca_csv(tmp_path), 2026) == 2
    session.commit()
    summary = eligibility.evaluate_all(session)
    session.commit()
    assert summary.by_verdict["eligible"] == 1 and summary.lca_loaded
    verdict = session.scalars(select(JobVerdict)).one()
    assert (verdict.verdict, verdict.sponsorship_level) == ("eligible", "B")
    evidence = verdict.sponsorship_json["items"][0]
    assert evidence["source_name"].startswith("US DOL") and "2 certified" in evidence["claim"]
    assert "1 for analyst" in evidence["claim"]

    digest = eligibility.build_digest(session)
    assert [c.title for c in digest.eligible] == ["Data Analyst"] and digest.eligible[0].official
    text = eligibility.digest_markdown(digest)
    assert "https://boards.greenhouse.io/acmefinancial/jobs/123" in text and "Level B" in text

    page = client.get("/today")
    assert page.status_code == 200
    assert 'href="https://boards.greenhouse.io/acmefinancial/jobs/123"' in page.text
    assert "Employer history found; role sponsorship unconfirmed" in page.text
    assert "Ask the recruiter" in page.text
    assert client.get("/today?family=product").text.count('data-testid="os2-card"') == 0


def test_posting_that_refuses_sponsorship_is_rejected_and_hidden(session, client, tmp_path):
    _profile(session)
    feeds = Feeds()
    feeds.gh[0]["content"] += "<p>We are unable to sponsor visas for this position.</p>"
    run_source(session, _source(session, "greenhouse", "acmefinancial", "Acme Financial"), feeds)
    lca.import_file(session, _lca_csv(tmp_path), 2026)
    eligibility.evaluate_all(session)
    session.commit()
    verdict = session.scalars(select(JobVerdict)).one()
    assert (verdict.verdict, verdict.sponsorship_level) == ("rejected", "D")
    assert "unable to sponsor" in verdict.sponsorship_json["items"][0]["quote"].lower()
    page = client.get("/today").text
    assert 'data-testid="os2-card"' not in page and "Sponsorship pathway" in page


def test_unconfirmed_profile_and_missing_lca_are_called_out(session, client):
    _profile(session, confirmed=False)
    run_source(session, _source(session, "greenhouse", "acmefinancial", "Acme Financial"), Feeds())
    eligibility.evaluate_all(session)
    session.commit()
    assert session.scalars(select(JobVerdict)).one().verdict == "research"
    page = client.get("/today").text
    assert "LCA history is not imported yet" in page
    assert "sponsorship need is not confirmed" in page


def test_seen_only_items_refresh_last_seen_without_renormalizing(session):
    from careeros.modules.sources.adapters import ADAPTERS

    info = {
        "title": "Data Analyst I",
        "jobDescription": "<p>Entry level</p>",
        "location": "Boston, MA",
        "timeType": "Full time",
        "startDate": "2026-11-09",
    }
    posting = {"title": "Data Analyst I", "externalPath": "/job/Boston/DA_R1"}

    class Workday:
        details = 0

        def get_text(self, url, **kwargs):
            return "User-agent: *\nAllow: /\n", 200

        def post_json(self, url, body, **kwargs):
            return {"total": 1, "jobPostings": [dict(posting)]}, 200

        def get_json(self, url, **kwargs):
            Workday.details += 1
            return {"jobPostingInfo": dict(info)}, 200

    ADAPTERS["workday"]._robots.clear()  # type: ignore[attr-defined]
    source = _source(session, "workday", "acme.wd5.Careers", "Acme")
    assert run_source(session, source, Workday()).new == 1
    first = session.scalars(select(Job)).one().last_seen_at
    session.execute(Source.__table__.update().values(last_success_at=None))
    from careeros.db.models import SourceRun

    session.query(SourceRun).delete()  # allow an immediate second run in the test
    session.commit()
    second = run_source(session, source, Workday())
    assert (second.new, second.updated, second.closed) == (0, 0, 0)
    assert Workday.details == 1  # the posting text was not fetched again
    assert session.scalars(select(Job)).one().last_seen_at >= first


def test_confirming_a_possible_legal_entity_raises_evidence_to_level_b(session, client, tmp_path):
    _profile(session)
    run_source(session, _source(session, "greenhouse", "acmefinancial", "Acme Financial"), Feeds())
    path = tmp_path / "LCA.csv"
    path.write_text(
        "CASE_STATUS,EMPLOYER_NAME,JOB_TITLE,SOC_TITLE\n"
        "Certified,Acme Financial Bank and Trust LLC,Data Analyst,Data Scientists\n"
    )
    lca.import_file(session, path, 2026)
    eligibility.evaluate_all(session)
    session.commit()
    verdict = session.scalars(select(JobVerdict)).one()
    assert (verdict.verdict, verdict.sponsorship_level) == ("research", "C")
    job_id = verdict.job_id
    page = client.get("/today").text
    assert 'value="acme financial bank and trust"' in page and "Confirm same employer" in page

    token = client.cookies.get("careeros_csrf") or ""
    bad = client.post(
        f"/today/jobs/{job_id}/confirm-employer", data={"filer": "invented", "csrf_token": token}
    )
    assert bad.status_code == 422
    ok = client.post(
        f"/today/jobs/{job_id}/confirm-employer",
        data={"filer": "acme financial bank and trust", "csrf_token": token},
        follow_redirects=False,
    )
    assert ok.status_code == 303
    session.expire_all()
    verdict = session.scalars(select(JobVerdict)).one()
    assert (verdict.verdict, verdict.sponsorship_level) == ("eligible", "B")
    assert "You confirmed" in verdict.sponsorship_json["items"][0]["claim"]
    page = client.get("/today").text
    assert "Prepare application" in page and "Confirm same employer" not in page


def test_overlapping_evaluators_do_not_collide_on_the_same_job(session, app):
    """The CLI and the background worker may evaluate the same jobs at the same moment."""
    _profile(session)
    run_source(session, _source(session, "greenhouse", "acmefinancial", "Acme Financial"), Feeds())
    session.commit()
    with app.state.session_factory() as other:
        eligibility.evaluate_all(other)  # second evaluator has written but not yet committed
        other.commit()
        eligibility.evaluate_all(session)  # first evaluator never saw that row being added
        session.commit()
    assert len(session.scalars(select(JobVerdict)).all()) == 1
