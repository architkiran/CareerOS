import httpx
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from careeros.modules.ingestion.service import run_all
from careeros.modules.sources import registry
from tests.conftest import post_form
from tests.helpers import GH_URL, make_fetcher


def test_sources_empty_state(client: TestClient) -> None:
    r = client.get("/sources")
    assert r.status_code == 200 and 'data-testid="sources-empty"' in r.text


def test_add_source_and_list(client: TestClient) -> None:
    r = post_form(
        client,
        "/sources",
        {"type": "lever", "token": "acme", "name": "Acme", "rate_limit_seconds": "3"},
    )
    assert r.status_code == 303
    page = client.get("/sources").text
    assert 'data-testid="source-row"' in page and "acme" in page and "Not checked yet" in page


def test_add_source_validation(client: TestClient) -> None:
    assert (
        post_form(client, "/sources", {"type": "linkedin", "token": "x", "name": "X"}).status_code
        == 422
    )
    r = post_form(client, "/sources", {"type": "lever", "token": "../etc", "name": "X"})
    assert r.status_code == 422 and "Board token" in r.text
    assert (
        post_form(
            client,
            "/sources",
            {"type": "lever", "token": "ok", "name": "X", "rate_limit_seconds": "0.1"},
        ).status_code
        == 422
    )


def test_duplicate_source_shows_error(client: TestClient) -> None:
    post_form(client, "/sources", {"type": "lever", "token": "acme", "name": "Acme"})
    r = post_form(client, "/sources", {"type": "lever", "token": "acme", "name": "Acme"})
    assert r.status_code == 422 and "already configured" in r.text


def test_toggle_source(app: FastAPI, client: TestClient) -> None:
    post_form(client, "/sources", {"type": "lever", "token": "acme", "name": "Acme"})
    with app.state.session_factory() as s:
        sid = registry.list_sources(s)[0].id
    post_form(client, f"/sources/{sid}/toggle", {})
    with app.state.session_factory() as s:
        assert registry.list_sources(s)[0].enabled is False
    post_form(client, f"/sources/{sid}/toggle", {"enabled": "on"})
    with app.state.session_factory() as s:
        assert registry.list_sources(s)[0].enabled is True
    assert post_form(client, "/sources/missing/toggle", {}).status_code == 404


@respx.mock
def test_failed_run_is_visible(app: FastAPI, client: TestClient) -> None:
    post_form(
        client, "/sources", {"type": "greenhouse", "token": "examplepay", "name": "ExamplePay"}
    )
    respx.get(GH_URL).mock(return_value=httpx.Response(404))
    run_all(app.state.session_factory, make_fetcher(max_attempts=1))
    page = client.get("/sources").text
    assert "failed" in page and "404" in page
    assert "task.failed" in client.get("/advanced/system").text
