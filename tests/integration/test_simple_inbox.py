import html
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import Application, Job, Task
from careeros.modules.jobs import inbox
from careeros.modules.system.settings_store import get_setting, set_setting
from tests.conftest import post_form
from tests.integration.test_fresh_referrals import make_role, match


def test_default_landing_and_exactly_three_primary_screens(client: TestClient) -> None:
    result = client.get("/", follow_redirects=False)
    assert result.status_code == 303 and result.headers["location"] == "/today"
    page = client.get("/new-jobs").text
    nav = page.split('data-testid="workspace-nav"')[1].split("</nav>")[0]
    assert nav.count("<a ") == 4
    assert all(label in nav for label in ("Today", "Saved", "Applications", "Resumes"))
    assert "Agent activity" not in page and "Mission Control" not in page
    assert "data-palette" in page and "data-core-inbox" in page


def test_direct_original_link_and_missing_url_state(session: Session, client: TestClient) -> None:
    good = make_role(session, "Usable posting", posted_at=utcnow() - timedelta(hours=1))
    good.canonical_url = "https://employer.example/jobs?id=abc&view=full#job"
    missing = make_role(session, "Missing link")
    missing.canonical_url = "https:///missing-host"
    session.commit()
    page = html.unescape(client.get("/new-jobs").text)
    assert 'href="https://employer.example/jobs?id=abc&view=full#job" target="_blank"' in page
    assert "View original posting" in page and "Original link unavailable" in page
    assert 'href="https:///missing-host"' not in page
    assert "Publication date unknown" in page and "Recently discovered" in page


def test_high_score_cannot_show_hard_failed_job(session: Session, client: TestClient) -> None:
    bad = make_role(session, "Failed but score 100")
    uncertain = make_role(session, "Eligible for review")
    match(session, bad, eligibility="fail", score=100)
    match(session, uncertain, eligibility="unknown", score=10)
    session.commit()
    page = client.get("/new-jobs").text
    assert "Failed but score 100" not in page and "Eligible for review" in page


def test_save_review_dismiss_and_safe_return(session: Session, client: TestClient) -> None:
    role = make_role(session)
    session.commit()
    response = post_form(
        client,
        f"/inbox/jobs/{role.id}/decision",
        {"action": "save", "return_to": "https://evil.example/"},
    )
    assert response.status_code == 303 and response.headers["location"] == "/new-jobs"
    assert role.title in client.get("/saved-jobs").text
    assert 'data-testid="core-job"' not in client.get("/new-jobs").text
    assert (
        post_form(
            client,
            f"/inbox/jobs/{role.id}/saved-status",
            {"stage": "reviewing", "next_action": "Check start date"},
        ).status_code
        == 303
    )
    assert "Check start date" in client.get("/saved-jobs").text
    assert (
        post_form(client, f"/inbox/jobs/{role.id}/decision", {"action": "dismiss"}).status_code
        == 303
    )
    saved = client.get("/saved-jobs").text
    assert "Rejected" in saved
    assert session.scalar(select(func.count()).select_from(Task)) == 0


def test_passive_poll_does_not_advance_last_visit(session: Session, client: TestClient) -> None:
    client.get("/new-jobs")
    session.expire_all()
    before = get_setting(session, "inbox.last_visit_at")
    client.get("/partials/inbox")
    session.expire_all()
    assert get_setting(session, "inbox.last_visit_at") == before


def test_visit_window_is_stable_then_uses_previous_visit(session: Session, monkeypatch) -> None:
    base = utcnow()
    monkeypatch.setattr(inbox, "utcnow", lambda: base)
    assert inbox.visit_cutoff(session, navigation=True) is None
    monkeypatch.setattr(inbox, "utcnow", lambda: base + timedelta(minutes=5))
    assert inbox.visit_cutoff(session, navigation=True) is None
    monkeypatch.setattr(inbox, "utcnow", lambda: base + timedelta(minutes=40))
    assert inbox.visit_cutoff(session, navigation=True) == base + timedelta(minutes=5)
    assert inbox.visit_cutoff(session, navigation=False) == base + timedelta(minutes=5)


def test_first_seen_since_previous_visit_and_review_page_scope(
    session: Session, client: TestClient
) -> None:
    now = utcnow()
    old = make_role(session, "Seen before previous visit", first_seen_at=now - timedelta(days=2))
    new = make_role(session, "Seen since previous visit", first_seen_at=now - timedelta(minutes=5))
    set_setting(session, "inbox.last_visit_at", (now - timedelta(days=1)).isoformat())
    session.commit()
    page = client.get("/new-jobs").text
    assert new.title in page and old.title not in page
    assert post_form(client, "/inbox/review-page", {"job_id": new.id}).status_code == 303
    session.expire_all()
    assert session.get(Job, old.id).triage_status == "new"
    assert session.get(Job, new.id).triage_status == "reviewed"


def test_source_date_order_excludes_future_as_publication(
    session: Session, client: TestClient
) -> None:
    first = make_role(
        session,
        "Latest known publication",
        posted_at=utcnow() - timedelta(minutes=10),
        first_seen_at=utcnow() - timedelta(days=1),
    )
    older = make_role(session, "Older source date", posted_at=utcnow() - timedelta(hours=2))
    future = make_role(
        session, "Unreliable future source date", posted_at=utcnow() + timedelta(days=5)
    )
    session.commit()
    page = client.get("/new-jobs").text
    assert page.index(first.title) < page.index(older.title) < page.index(future.title)
    assert "Publication date unknown" in page


def test_pagination_and_sponsorship_filter_are_applied_before_paging(
    session: Session, client: TestClient
) -> None:
    now = utcnow()
    for index in range(65):
        role = make_role(session, f"Analyst {index:03}")
        role.sponsorship_checked_at = now
        role.sponsorship_status = "confirmed" if index % 2 else "not_indicated"
    session.commit()
    page = client.get("/new-jobs").text
    assert page.count('data-testid="core-job"') == 50 and "Page 1 of 2" in page
    filtered = client.get("/new-jobs?sponsorship=confirmed").text
    assert filtered.count('data-testid="core-job"') == 32
    assert client.get("/new-jobs?page=2").text.count('data-testid="core-job"') == 15


def test_manual_record_goes_to_simple_tracker_not_preparation(
    session: Session, client: TestClient
) -> None:
    role = make_role(session)
    session.commit()
    assert (
        post_form(client, f"/inbox/jobs/{role.id}/decision", {"action": "save"}).status_code == 303
    )
    response = post_form(client, f"/jobs/{role.id}/record-applied", {"confirmed": "on"})
    assert response.status_code == 303
    record = client.get(response.headers["location"]).text
    assert "CareerOS did not submit it" in record and "Application notes" in record
    assert "Tailor with local AI" not in record
    tracker = client.get("/applications").text
    assert role.title in tracker and "Applied" in tracker
    assert session.scalar(select(func.count()).select_from(Application)) == 1
    assert session.scalar(select(func.count()).select_from(Task)) == 0


def test_schedule_settings_and_open_metric_require_csrf(
    session: Session, client: TestClient
) -> None:
    role = make_role(session)
    session.commit()
    assert client.post(f"/inbox/jobs/{role.id}/opened").status_code == 403
    assert post_form(client, f"/inbox/jobs/{role.id}/opened").status_code == 204
    assert post_form(client, "/inbox/schedule", {"minutes": "5"}).status_code == 422
    assert (
        post_form(client, "/inbox/schedule", {"minutes": "60", "enabled": "on"}).status_code == 303
    )
    session.expire_all()
    assert get_setting(session, "watch.interval_minutes") == 60
    assert get_setting(session, "watch.enabled") is True


def test_old_unknown_publication_is_not_labeled_recently_discovered(
    session: Session, client: TestClient
) -> None:
    make_role(session, "Older import", first_seen_at=utcnow() - timedelta(days=40))
    session.commit()
    page = client.get("/new-jobs").text
    assert "Older import" in page and "Publication date unknown" in page
    assert ">Recently discovered<" not in page


def test_disabled_source_errors_do_not_alarm_the_active_inbox(session: Session) -> None:
    from careeros.modules.sources.registry import SourceIn, add_source

    active = add_source(session, SourceIn(type="greenhouse", token="current", name="Current"))
    disabled = add_source(session, SourceIn(type="greenhouse", token="old", name="Old"))
    disabled.enabled = False
    disabled.last_error = "Historical 404"
    active.last_success_at = utcnow() - timedelta(minutes=5)
    disabled.last_success_at = utcnow()
    session.flush()
    overview = inbox.refresh_overview(session)
    assert overview["source_count"] == 1
    assert overview["errors"] == []
    assert overview["last_success"] == active.last_success_at


def test_verified_last_day_excludes_board_republishes_old_and_unknown_dates(
    session: Session, client: TestClient
) -> None:
    for title, kind, age in [
        ("Original recent", "original", 1),
        ("Board recent", "provider_reported", 1),
        ("Employer republished", "last_publication", 1),
        ("Old original", "original", 1000),
    ]:
        role = make_role(session, title, posted_at=utcnow() - timedelta(hours=age))
        role.publication_kind = kind
    make_role(session, "Unknown publication")
    session.commit()
    page = client.get("/new-jobs?mode=fresh").text
    assert "Original recent" in page
    for title in ["Board recent", "Employer republished", "Old original", "Unknown publication"]:
        assert f"<h2>{title}</h2>" not in page


def test_aggregator_date_is_not_presented_as_original_publication(
    session: Session, client: TestClient
) -> None:
    role = make_role(session, "Board date only", posted_at=utcnow() - timedelta(hours=1))
    role.publication_kind = "provider_reported"
    session.commit()
    page = client.get("/new-jobs").text
    assert "Publication date unknown" in page
    assert "Provider date (provider_reported)" in page
    assert ">New</span>" not in page
