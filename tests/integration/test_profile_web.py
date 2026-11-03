import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from careeros.modules.profile import service
from tests.conftest import csrf_token, post_form


def _profile(app: FastAPI):  # type: ignore[no-untyped-def]
    with app.state.session_factory() as s:
        p = service.get_profile(s)
        return (p, service.list_facts(s, p.id) if p else [])


# ---------- CSRF ----------


def test_post_without_csrf_token_rejected(client: TestClient) -> None:
    r = client.post("/profile", data={"display_name": "X"})
    assert r.status_code == 403


def test_post_with_wrong_csrf_token_rejected(client: TestClient) -> None:
    csrf_token(client)
    r = client.post("/profile", data={"display_name": "X", "csrf_token": "forged"})
    assert r.status_code == 403


def test_post_with_csrf_header_accepted(client: TestClient) -> None:
    r = client.post(
        "/profile",
        data={"display_name": "Header"},
        headers={"X-CSRF-Token": csrf_token(client)},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_csrf_cookie_is_httponly_strict(client: TestClient) -> None:
    r = client.get("/profile")
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


# ---------- pages and empty states ----------


def test_profile_page_empty_state(client: TestClient) -> None:
    r = client.get("/profile")
    assert r.status_code == 200
    assert 'data-testid="facts-empty"' in r.text
    assert "Create your profile" in r.text


def test_lanes_page_empty_state(client: TestClient) -> None:
    assert 'data-testid="lanes-empty"' in client.get("/lanes").text


def test_nav_links_present(client: TestClient) -> None:
    html = client.get("/").text
    assert 'href="/profile"' in html and 'href="/lanes"' in html


# ---------- basics ----------


def test_save_basics(app: FastAPI, client: TestClient) -> None:
    r = post_form(
        client,
        "/profile",
        {
            "display_name": "Ada",
            "email": "ada@example.com",
            "open_to_relocation": "yes",
            "relocation_locations": "NYC, Chicago",
            "graduation_date": "2026-12-15",
            "salary_floor": "75000",
        },
    )
    assert r.status_code == 303 and r.headers["location"] == "/profile?saved=basics"
    page = client.get("/profile?saved=basics").text
    assert 'data-testid="saved"' in page and 'value="Ada"' in page and "NYC, Chicago" in page
    profile, _ = _profile(app)
    assert profile.salary_floor == 75000


def test_invalid_basics_show_errors_and_do_not_save(app: FastAPI, client: TestClient) -> None:
    r = post_form(
        client, "/profile", {"display_name": "Bad", "email": "nope", "salary_floor": "-1"}
    )
    assert r.status_code == 422
    assert 'data-testid="form-errors"' in r.text and "valid email" in r.text
    profile, _ = _profile(app)
    assert profile is None or profile.display_name != "Bad"


def test_non_numeric_salary_rejected(client: TestClient) -> None:
    r = post_form(client, "/profile", {"salary_floor": "lots"})
    assert r.status_code == 422


# ---------- facts ----------


def test_add_verify_unverify_delete_fact(app: FastAPI, client: TestClient) -> None:
    r = post_form(
        client,
        "/profile/facts",
        {
            "category": "education",
            "fact_key": "Degree",
            "fact_value": "MS Computer Science",
            "verified": "on",
        },
    )
    assert r.status_code == 303
    _, facts = _profile(app)
    fact = facts[0]
    assert fact.verified_status == "verified"
    assert "pill-verified" in client.get("/profile").text

    post_form(client, f"/profile/facts/{fact.id}/verify", {"status": "unverified"})
    assert _profile(app)[1][0].verified_status == "unverified"

    post_form(client, f"/profile/facts/{fact.id}/delete")
    assert _profile(app)[1] == []


def test_fact_value_is_escaped(client: TestClient) -> None:
    post_form(
        client,
        "/profile/facts",
        {"category": "other", "fact_key": "x", "fact_value": "<img src=x onerror=alert(1)>"},
    )
    html = client.get("/profile").text
    assert "<img src=x" not in html and "&lt;img src=x" in html


def test_fact_missing_value_rejected(client: TestClient) -> None:
    r = post_form(client, "/profile/facts", {"category": "education", "fact_key": "Degree"})
    assert r.status_code == 422


def test_unknown_kind_and_missing_item_404(client: TestClient) -> None:
    assert post_form(client, "/profile/gossip/abc/verify").status_code == 404
    assert post_form(client, "/profile/facts/missing/delete").status_code == 404


# ---------- skills / experience / projects ----------


def test_duplicate_skill_shows_error(client: TestClient) -> None:
    assert post_form(client, "/profile/skills", {"name": "SQL"}).status_code == 303
    r = post_form(client, "/profile/skills", {"name": "sql"})
    assert r.status_code == 422 and "already on your profile" in r.text


def test_experience_bad_dates_rejected(client: TestClient) -> None:
    r = post_form(
        client,
        "/profile/experience",
        {
            "title": "Analyst",
            "organization": "Org",
            "start_date": "2024-06-01",
            "end_date": "2024-01-01",
        },
    )
    assert r.status_code == 422 and "End date" in r.text


def test_project_outcomes_one_per_line(app: FastAPI, client: TestClient) -> None:
    post_form(
        client,
        "/profile/projects",
        {
            "name": "Pipeline",
            "technologies": "Python, SQL",
            "outcomes": "Built ingestion\n\nAdded tests\n",
        },
    )
    with app.state.session_factory() as s:
        p = service.get_or_create_profile(s)
        proj = service.list_projects(s, p.id)[0]
        assert proj.outcomes_json == ["Built ingestion", "Added tests"]
        assert proj.technologies_json == ["Python", "SQL"]


# ---------- lanes ----------


def test_add_default_lanes_then_edit(app: FastAPI, client: TestClient) -> None:
    assert post_form(client, "/lanes/defaults").headers["location"] == "/lanes?saved=defaults-6"
    assert post_form(client, "/lanes/defaults").headers["location"] == "/lanes?saved=defaults-0"
    with app.state.session_factory() as s:
        lane = service.list_lanes(s)[0]
    weights = {f"w_{k}": v for k, v in service.lane_weights(lane).model_dump().items()}
    r = post_form(
        client,
        f"/lanes/{lane.id}",
        {
            "name": "Renamed lane",
            "enabled": "on",
            "title_keywords": "analyst, data",
            "seniority_allowed": ["entry", "junior"],
            **weights,
        },
    )
    assert r.status_code == 303
    with app.state.session_factory() as s:
        updated = service.list_lanes(s)
        renamed = next(x for x in updated if x.id == lane.id)
        assert renamed.name == "Renamed lane"
        assert service.lane_rules(renamed).seniority_allowed == ["entry", "junior"]
        assert service.lane_rules(renamed).title_keywords == ["analyst", "data"]


def test_lane_weights_not_100_rejected(app: FastAPI, client: TestClient) -> None:
    r = post_form(client, "/lanes", {"name": "Broken", "w_role_title": "50", "w_skills": "60"})
    assert r.status_code == 422 and "add up to 100" in r.text
    with app.state.session_factory() as s:
        assert service.list_lanes(s) == []


def test_toggle_lane(app: FastAPI, client: TestClient) -> None:
    post_form(client, "/lanes/defaults")
    with app.state.session_factory() as s:
        lane_id = service.list_lanes(s)[0].id
    post_form(client, f"/lanes/{lane_id}/toggle", {})  # unchecked checkbox → disabled
    with app.state.session_factory() as s:
        assert s.get(type(service.list_lanes(s)[0]), lane_id).enabled is False  # type: ignore[union-attr]


def test_toggle_missing_lane_404(client: TestClient) -> None:
    assert post_form(client, "/lanes/missing/toggle").status_code == 404


# ---------- work authorization ----------


def test_work_authorization_flow_and_privacy(client: TestClient) -> None:
    page = client.get("/profile/work-authorization").text
    assert "Not confirmed" in page
    r = post_form(
        client,
        "/profile/work-authorization",
        {
            "status_text": "PRIVATE-WA-VALUE",
            "requires_sponsorship_now": "no",
            "requires_sponsorship_future": "unknown",
            "confirmed": "on",
        },
    )
    assert r.status_code == 303
    page = client.get("/profile/work-authorization").text
    assert "PRIVATE-WA-VALUE" in page and "Confirmed" in page
    assert "PRIVATE-WA-VALUE" not in client.get("/").text  # never in activity feed
    assert "PRIVATE-WA-VALUE" not in client.get("/profile/export.json").text


def test_work_authorization_invalid_choice(client: TestClient) -> None:
    r = post_form(client, "/profile/work-authorization", {"requires_sponsorship_now": "maybe"})
    assert r.status_code == 422


# ---------- export / import ----------


def test_export_404_without_profile(client: TestClient) -> None:
    assert client.get("/profile/export.json").status_code == 404


def test_export_then_import_replace(app: FastAPI, client: TestClient) -> None:
    post_form(client, "/profile", {"display_name": "Exported"})
    post_form(client, "/profile/skills", {"name": "Python", "verified": "on"})
    r = client.get("/profile/export.json")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store"
    body = r.content

    blocked = post_form(
        client, "/profile/import", files={"file": ("p.json", body, "application/json")}
    )
    assert blocked.status_code == 422 and "already exists" in blocked.text

    ok = post_form(
        client,
        "/profile/import",
        {"replace": "on"},
        files={"file": ("p.json", body, "application/json")},
    )
    assert ok.status_code == 303
    assert json.loads(client.get("/profile/export.json").content)["skills"][0]["name"] == "Python"


def test_import_rejects_bad_files(client: TestClient) -> None:
    r = post_form(
        client, "/profile/import", files={"file": ("p.json", b"{not json", "application/json")}
    )
    assert r.status_code == 422 and "not valid JSON" in r.text
    r = post_form(
        client,
        "/profile/import",
        files={
            "file": (
                "p.json",
                json.dumps({"schema_version": 99, "profile": {}}).encode(),
                "application/json",
            )
        },
    )
    assert r.status_code == 422
    r = post_form(
        client, "/profile/import", files={"file": ("p.json", b" " * 2_000_001, "application/json")}
    )
    assert r.status_code == 422 and "too large" in r.text
    r = post_form(client, "/profile/import")
    assert r.status_code == 422 and "Choose a JSON file" in r.text


def test_profile_changes_appear_in_activity_feed(client: TestClient) -> None:
    post_form(client, "/profile", {"display_name": "Feed"})
    html = client.get("/").text
    assert "profile.updated" in html
