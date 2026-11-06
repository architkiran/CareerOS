import httpx
import pytest

from careeros.local_launcher import probe


@pytest.mark.parametrize(
    "case,expected",
    [
        ("ready", "ready"),
        ("missing", "absent"),
        ("other", "occupied"),
        ("broken", "occupied"),
        ("timeout", "occupied"),
        ("badjson", "occupied"),
    ],
)
def test_launcher_reuses_only_a_healthy_careeros_server(case, expected):  # type: ignore[no-untyped-def]
    def handle(request):
        if case == "missing":
            raise httpx.ConnectError("refused", request=request)
        if case == "timeout":
            raise httpx.ReadTimeout("busy", request=request)
        if case == "other":
            return httpx.Response(200, json={"service": "other"})
        if case == "badjson":
            return httpx.Response(200, text="not JSON")
        if request.url.path == "/health":
            return httpx.Response(200, json={"version": "0.1.0", "database": {}, "schema": {}})
        return httpx.Response(500 if case == "broken" else 200, text="data-mission-live")

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert probe(client, "http://127.0.0.1:8766") == expected


@pytest.mark.parametrize("state,result", [("ready", 0), ("occupied", 1)])
def test_launch_does_not_start_a_duplicate_worker(monkeypatch, capsys, state, result):  # type: ignore[no-untyped-def]
    import careeros.local_launcher as launcher

    monkeypatch.setattr(launcher, "probe", lambda *args: state)
    calls = []
    monkeypatch.setattr(launcher.os, "execv", lambda *args: calls.append(args))
    assert launcher.main() == result and calls == []
    message = capsys.readouterr().out
    assert ("already running" if state == "ready" else "occupied") in message
