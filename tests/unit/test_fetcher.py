import httpx
import pytest
import respx

from careeros.modules.sources.adapters import ADAPTERS
from careeros.modules.sources.http import FetchError, SourceBlockedError, SourceNotFoundError
from tests.helpers import FakeClock, make_fetcher

URL = "https://api.example-ats.test/jobs"


@respx.mock
def test_success_returns_json_and_sends_user_agent() -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    data, status = make_fetcher().get_json(URL)
    assert (data, status) == ({"ok": True}, 200)
    assert "CareerOS" in route.calls[0].request.headers["user-agent"]


@respx.mock
def test_retries_server_error_then_succeeds() -> None:
    respx.get(URL).mock(side_effect=[httpx.Response(503), httpx.Response(200, json=[])])
    clock = FakeClock()
    assert make_fetcher(clock).get_json(URL, min_interval=0)[0] == []
    assert len(clock.sleeps) == 1 and clock.sleeps[0] >= 1.0


@respx.mock
def test_gives_up_after_max_attempts() -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(500))
    with pytest.raises(FetchError, match="Server error 500"):
        make_fetcher(max_attempts=3).get_json(URL)
    assert route.call_count == 3


@respx.mock
def test_backoff_grows_and_is_capped() -> None:
    respx.get(URL).mock(return_value=httpx.Response(502))
    clock = FakeClock()
    with pytest.raises(FetchError):
        make_fetcher(clock, max_attempts=4, backoff_base_seconds=1, backoff_max_seconds=3).get_json(
            URL, min_interval=0
        )
    assert len(clock.sleeps) == 3
    assert clock.sleeps[0] < clock.sleeps[1] <= 3 and max(clock.sleeps) <= 3


@respx.mock
def test_429_honours_retry_after_then_raises_blocked() -> None:
    respx.get(URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "7"}))
    clock = FakeClock()
    with pytest.raises(SourceBlockedError):
        make_fetcher(clock, max_attempts=2).get_json(URL, min_interval=0)
    assert clock.sleeps == [7.0]


@respx.mock
def test_retry_after_capped() -> None:
    respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "9999"}),
            httpx.Response(200, json={}),
        ]
    )
    clock = FakeClock()
    make_fetcher(clock, max_retry_after_seconds=60).get_json(URL, min_interval=0)
    assert clock.sleeps == [60.0]


@respx.mock
def test_403_is_not_retried() -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(403))
    with pytest.raises(SourceBlockedError) as info:
        make_fetcher().get_json(URL)
    assert info.value.status_code == 403 and route.call_count == 1


@respx.mock
def test_404_raises_not_found() -> None:
    respx.get(URL).mock(return_value=httpx.Response(404))
    with pytest.raises(SourceNotFoundError):
        make_fetcher().get_json(URL)


@respx.mock
def test_other_4xx_not_retried() -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(400))
    with pytest.raises(FetchError, match="400"):
        make_fetcher().get_json(URL)
    assert route.call_count == 1


@respx.mock
def test_timeout_retried_then_error() -> None:
    route = respx.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(FetchError, match="Timed out"):
        make_fetcher(max_attempts=2).get_json(URL)
    assert route.call_count == 2


@respx.mock
def test_connection_error() -> None:
    respx.get(URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(FetchError, match="Network error"):
        make_fetcher(max_attempts=1).get_json(URL)


@respx.mock
def test_invalid_json() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"<html>"))
    with pytest.raises(FetchError, match="not valid JSON"):
        make_fetcher().get_json(URL)


@respx.mock
def test_oversized_response_rejected() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"[" + b"1," * 100 + b"1]"))
    with pytest.raises(FetchError, match="size limit"):
        make_fetcher(max_response_bytes=50).get_json(URL)


@respx.mock
def test_retry_also_respects_rate_limit() -> None:
    respx.get(URL).mock(side_effect=[httpx.Response(503), httpx.Response(200, json={})])
    clock = FakeClock()
    make_fetcher(clock, backoff_base_seconds=0.1).get_json(URL, min_interval=5)
    assert sum(clock.sleeps) == pytest.approx(5)  # backoff plus top-up to the 5s interval


@respx.mock
def test_per_domain_rate_limit() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json={}))
    respx.get("https://other.test/x").mock(return_value=httpx.Response(200, json={}))
    clock = FakeClock()
    f = make_fetcher(clock)
    f.get_json(URL, min_interval=5)
    f.get_json("https://other.test/x", min_interval=5)
    assert clock.sleeps == []  # different host, no wait
    clock.now += 1
    f.get_json(URL, min_interval=5)
    assert clock.sleeps == [pytest.approx(4)]


@respx.mock
def test_lever_paginates_until_short_page() -> None:
    page = [{"id": str(i)} for i in range(100)]
    route = respx.get("https://api.lever.co/v0/postings/acme").mock(
        side_effect=[httpx.Response(200, json=page), httpx.Response(200, json=page[:3])]
    )
    items, _ = ADAPTERS["lever"].fetch_raw(make_fetcher(), "acme", 0.5)
    assert len(items) == 103 and route.call_count == 2
    assert route.calls[1].request.url.params["skip"] == "100"


@respx.mock
def test_ashby_skips_unlisted() -> None:
    from tests.helpers import ASHBY_URL, load_fixture

    respx.get(ASHBY_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("ashby_jobs.json"))
    )
    items, _ = ADAPTERS["ashby"].fetch_raw(make_fetcher(), "examplecard", 0.5)
    assert [i["title"] for i in items] == ["Product Analyst", "Analytics Engineer"]
