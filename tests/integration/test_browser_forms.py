"""Regression tests that submit forms exactly the way a browser does (empty fields included)."""

from fastapi.testclient import TestClient

BROWSER_INBOX_QUERY = (
    "/jobs?q=&triage=&status=active&source_id=&workplace=&days=&lane_id="
    "&eligibility=not_fail&min_score=&sort=newest"
)


def test_inbox_filter_form_with_empty_fields(client: TestClient) -> None:
    r = client.get(BROWSER_INBOX_QUERY)
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]


def test_inbox_garbage_numbers_are_ignored(client: TestClient) -> None:
    r = client.get("/jobs?days=abc&min_score=lots&page=x")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]


HTML = {"accept": "text/html,application/xhtml+xml"}


def test_404_is_a_page_for_browsers(client: TestClient) -> None:
    r = client.get("/jobs/does-not-exist", headers=HTML)
    assert r.status_code == 404 and "text/html" in r.headers["content-type"]
    assert 'data-testid="error-page"' in r.text and "Job not found" in r.text


def test_unknown_url_is_a_page(client: TestClient) -> None:
    r = client.get("/no/such/page", headers=HTML)
    assert r.status_code == 404 and 'data-testid="error-page"' in r.text


def test_csrf_failure_is_a_page_with_hint(client: TestClient) -> None:
    r = client.post("/profile", data={"display_name": "x"}, headers=HTML)
    assert r.status_code == 403 and "Reload the page" in r.text


def test_plain_form_post_without_accept_gets_html(client: TestClient) -> None:
    r = client.post("/profile", data={"display_name": "x"})
    assert r.status_code == 403 and "text/html" in r.headers["content-type"]


def test_validation_error_page_lists_fields(client: TestClient) -> None:
    r = client.get("/events/stream?after=-5", headers=HTML)  # machine endpoint keeps JSON
    assert r.status_code == 422 and r.headers["content-type"].startswith("application/json")


def test_health_and_feed_stay_json(client: TestClient) -> None:
    assert (
        client.get("/health", headers=HTML).headers["content-type"].startswith("application/json")
    )
    assert (
        client.get("/events/feed", headers=HTML)
        .headers["content-type"]
        .startswith("application/json")
    )
    r = client.get("/jobs/x", headers={"accept": "application/json"})
    assert r.status_code == 404 and r.json() == {"detail": "Job not found"}


def test_error_page_back_link_only_same_origin(client: TestClient) -> None:
    r = client.get("/jobs/missing", headers=HTML | {"referer": "https://evil.example/x"})
    assert "evil.example" not in r.text
    r = client.get("/jobs/missing", headers=HTML | {"referer": "http://testserver/jobs"})
    assert 'href="http://testserver/jobs"' in r.text


def test_bounded_int() -> None:
    from careeros.web.forms import bounded_int

    assert bounded_int(None, 0, 10) is None and bounded_int("  ", 0, 10) is None
    assert bounded_int("5", 0, 10) == 5 and bounded_int("11", 0, 10) is None
    assert bounded_int("abc", 0, 10) is None and bounded_int(" 7 ", 0, 10) == 7


def test_inbox_valid_numbers_still_apply(client: TestClient) -> None:
    html = client.get("/jobs?days=7&min_score=50&eligibility=any").text
    assert 'value="50"' in html and '<option value="7" selected>' in html
