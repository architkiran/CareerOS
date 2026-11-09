"""Real database/HTTP checks for source-dated discovery and draft-only referral paths."""

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import (
    Application,
    CandidateProfile,
    Company,
    Job,
    JobLaneMatch,
    OutreachContact,
    OutreachDraft,
    Project,
    ReferralPath,
    RoleLane,
)
from careeros.modules.jobs.service import JobFilters, list_jobs
from careeros.modules.referrals import service
from tests.conftest import post_form


def make_role(session: Session, title: str = "Data Analyst", **kw: object) -> Job:
    company = session.scalar(select(Company).where(Company.canonical_name == "Example Finance"))
    if not company:
        company = Company(canonical_name="Example Finance", normalized_name="example finance")
        session.add(company)
        session.flush()
    job = Job(
        company_id=company.id,
        title=title,
        normalized_title=title.lower(),
        canonical_url="https://example.test/jobs/analyst",
        description_text="SQL analytics",
        description_hash=title,
        dedupe_key=title,
        **kw,
    )
    session.add(job)
    session.flush()
    return job


def match(session: Session, job: Job, eligibility: str = "unknown", score: int = 20) -> None:
    lane = session.scalar(select(RoleLane).limit(1))
    if not lane:
        lane = RoleLane(name="Data Analyst")
        session.add(lane)
        session.flush()
    session.add(
        JobLaneMatch(
            job_id=job.id,
            role_lane_id=lane.id,
            classified=True,
            eligibility=eligibility,
            score=score,
            completeness=50,
            score_breakdown_json={},
            hard_filter_results_json=[],
            explanation="Authorization requires review",
            algorithm_version="test",
            input_hash=job.id,
        )
    )
    session.flush()


def test_source_dates_not_import_dates_control_order_and_window(session: Session) -> None:
    now = utcnow()
    just_published = make_role(
        session,
        "Recently published",
        posted_at=now - timedelta(minutes=10),
        first_seen_at=now - timedelta(days=3),
    )
    older = make_role(
        session, "Recent import", posted_at=now - timedelta(hours=20), first_seen_at=now
    )
    stale = make_role(session, "Old posting", posted_at=now - timedelta(days=8), first_seen_at=now)
    future = make_role(session, "Future timestamp", posted_at=now + timedelta(hours=1))
    unknown = make_role(session, "No source date", posted_at=None)
    for job in (just_published, older, stale, future, unknown):
        match(session, job)
    rows, count = list_jobs(
        session, JobFilters(recommended=True, published_minutes=1440, sort="published")
    )
    assert count == 2
    assert [r.job.id for r in rows] == [just_published.id, older.id]


def test_fresh_http_keeps_low_scoring_review_roles_but_hides_failures(
    session: Session, client: TestClient
) -> None:
    good = make_role(session, "Low score, needs review", posted_at=utcnow() - timedelta(minutes=5))
    fail = make_role(session, "Explicitly ineligible", posted_at=utcnow() - timedelta(minutes=2))
    match(session, good, score=10)
    match(session, fail, "fail", score=95)
    session.commit()
    response = client.get("/jobs?view=fresh")
    assert response.status_code == 200
    assert "Low score, needs review" in response.text
    assert "Explicitly ineligible" not in response.text
    assert "Eligibility review needed" in response.text
    assert f"/referrals?job_id={good.id}" in response.text
    assert "Fresh openings" in response.text


def test_referral_empty_state_and_bad_job(client: TestClient) -> None:
    assert "Pick a role to find a way in" in client.get("/referrals").text
    assert client.get("/referrals?job_id=missing").status_code == 404
    assert post_form(client, "/referrals/missing/paths").status_code == 404


def test_save_reuse_and_edit_referral_without_application(
    session: Session, client: TestClient
) -> None:
    job = make_role(session)
    session.commit()
    data = {
        "name": "Example Employee",
        "role": "Analyst",
        "public_profile_url": "https://www.linkedin.com/in/example",
        "relationship": "introduction",
        "via": "A known classmate",
        "notes": "Ask first",
    }
    for _ in range(2):
        assert post_form(client, f"/referrals/{job.id}/paths", data).status_code == 303
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(OutreachContact)) == 1
    paths = list(session.scalars(select(ReferralPath)))
    assert len(paths) == 1 and paths[0].status == "identified"
    assert session.scalar(select(func.count()).select_from(Application)) == 0
    assert session.scalar(select(func.count()).select_from(OutreachDraft)) == 0
    response = client.get(f"/referrals?job_id={job.id}")
    assert "A known classmate" in response.text and "Example Employee" in response.text
    assert (
        post_form(
            client, f"/referrals/paths/{paths[0].id}/status", {"status": "requested"}
        ).status_code
        == 303
    )
    session.expire_all()
    assert session.get(ReferralPath, paths[0].id).status == "requested"


def test_cannot_attach_contact_from_another_company(session: Session, client: TestClient) -> None:
    job = make_role(session)
    other = Company(canonical_name="Other Co", normalized_name="other co")
    session.add(other)
    session.flush()
    person = OutreachContact(company_id=other.id, name="Other employee")
    session.add(person)
    session.commit()
    response = post_form(client, f"/referrals/{job.id}/paths", {"contact_id": person.id})
    assert response.status_code == 422
    assert session.scalar(select(func.count()).select_from(ReferralPath)) == 0


@pytest.mark.parametrize(
    "data",
    [
        {"name": "Bad", "public_profile_url": "javascript:alert(1)"},
        {"name": "Bad", "relationship": "invented"},
        {"name": "Bad", "via": "x" * 201},
        {"name": ""},
    ],
)
def test_invalid_referral_forms_are_atomic(
    session: Session, client: TestClient, data: dict
) -> None:
    job = make_role(session)
    session.commit()
    assert post_form(client, f"/referrals/{job.id}/paths", data).status_code == 422
    assert session.scalar(select(func.count()).select_from(OutreachContact)) == 0
    assert session.scalar(select(func.count()).select_from(ReferralPath)) == 0


def test_private_draft_uses_verified_evidence_and_does_not_change_status(
    session: Session, client: TestClient
) -> None:
    job = make_role(session)
    person = OutreachContact(company_id=job.company_id, name="Example Employee")
    candidate = CandidateProfile(display_name="Candidate Name")
    session.add_all((person, candidate))
    session.flush()
    session.add_all(
        [
            Project(
                profile_id=candidate.id, name="Verified SQL project", verified_status="verified"
            ),
            Project(
                profile_id=candidate.id, name="Fabricated unicorn", verified_status="unverified"
            ),
        ]
    )
    path = service.save_path(session, job.id, person.id, service.PathIn())
    session.commit()
    assert post_form(client, f"/referrals/paths/{path.id}/draft").status_code == 303
    session.expire_all()
    path = session.get(ReferralPath, path.id)
    draft = session.get(OutreachDraft, path.draft_id)
    assert path.status == "identified" and draft.status == "draft"
    body = Path(draft.body_path).read_text()
    assert "Verified SQL project" in body and job.canonical_url in body
    assert "Fabricated unicorn" not in body
    assert "comfortable referring me" in body
    assert Path(draft.body_path).stat().st_mode & 0o777 == 0o600
    assert (
        post_form(
            client, f"/referrals/paths/{path.id}/draft", {"body": "My edited request"}
        ).status_code
        == 303
    )
    assert Path(draft.body_path).read_text() == "My edited request"
    assert post_form(client, f"/referrals/paths/{path.id}/draft", {"body": ""}).status_code == 422
    assert Path(draft.body_path).read_text() == "My edited request"


def test_referral_csrf_and_unknown_status(session: Session, client: TestClient) -> None:
    job = make_role(session)
    person = OutreachContact(company_id=job.company_id, name="Example")
    session.add(person)
    session.flush()
    path = service.save_path(session, job.id, person.id, service.PathIn())
    session.commit()
    assert client.post(f"/referrals/{job.id}/paths", data={"name": "No token"}).status_code == 403
    assert (
        post_form(
            client, f"/referrals/paths/{path.id}/status", {"status": "sent_automatically"}
        ).status_code
        == 422
    )
    assert post_form(client, "/referrals/paths/missing/draft").status_code == 404


def test_search_links_are_encoded_and_not_labeled_as_people() -> None:
    links = service.search_links("A&B", "Data / Analyst")
    assert "A%26B" in links[0]["url"]
    assert any("bu.edu" in link["url"] for link in links)
    assert all("hint" in link for link in links)


def test_saved_role_stays_accessible_after_matching_rules_it_out(
    session: Session, client: TestClient
) -> None:
    role = make_role(session, "Saved for a connection", triage_status="saved", status="closed")
    match(session, role, eligibility="fail")
    session.commit()
    html = client.get("/referrals").text
    assert role.title in html
    assert "Closed in feed" in html


def test_referral_page_escapes_person_and_notes(session: Session, client: TestClient) -> None:
    role = make_role(session)
    session.commit()
    assert (
        post_form(
            client,
            f"/referrals/{role.id}/paths",
            {"name": "<script>person()</script>", "notes": "<script>notes()</script>"},
        ).status_code
        == 303
    )
    html = client.get(f"/referrals?job_id={role.id}").text
    assert "<script>person()" not in html and "&lt;script&gt;person()" in html
    assert "<script>notes()" not in html and "&lt;script&gt;notes()" in html


def test_tracked_path_stays_accessible_even_if_role_is_no_longer_matched(
    session: Session, client: TestClient
) -> None:
    role = make_role(session, "Previously relevant role", status="closed")
    person = OutreachContact(company_id=role.company_id, name="A real contact")
    session.add(person)
    session.flush()
    service.save_path(session, role.id, person.id, service.PathIn())
    session.commit()
    html = client.get("/referrals").text
    assert role.title in html and "A real contact" in html


def test_review_reasons_visible_before_referral_request(
    session: Session, client: TestClient
) -> None:
    job = make_role(session, posted_at=utcnow())
    match(session, job)
    m = session.scalar(select(JobLaneMatch).where(JobLaneMatch.job_id == job.id))
    m.hard_filter_results_json = [
        {
            "name": "work_authorization",
            "decision": "unknown",
            "reason": "Posting will not sponsor; review your status.",
            "evidence": "No visa sponsorship for this position.",
        }
    ]
    session.commit()
    for url in (f"/jobs?view=fresh&selected={job.id}", f"/referrals?job_id={job.id}"):
        html = client.get(url).text
        assert "Review before pursuing" in html
        assert "No visa sponsorship for this position." in html
        assert "review your status" in html
