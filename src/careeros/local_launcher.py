"""Reuse a running local CareerOS server before starting another worker/server."""

import os
import socket
import sys
from typing import Literal

import httpx

from careeros.config import get_settings

Probe = Literal["ready", "absent", "occupied"]


def probe(client: httpx.Client, url: str) -> Probe:
    try:
        health = client.get(url + "/health")
        if health.status_code != 200:
            return "occupied"
        data = health.json()
        if not isinstance(data, dict) or not {"version", "database", "schema"} <= data.keys():
            return "occupied"
        page = client.get(url + "/mission-control")
        return (
            "ready" if page.status_code == 200 and "data-mission-live" in page.text else "occupied"
        )
    except httpx.ConnectError:
        return "absent"
    except (httpx.HTTPError, ValueError):
        return "occupied"


def main() -> int:
    port = get_settings().app_port
    url = f"http://127.0.0.1:{port}"
    with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
        state = probe(client, url)
    if state == "absent":
        try:
            with socket.socket() as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", port))
        except OSError:
            state = "occupied"
    if state == "ready":
        print(f"CareerOS is already running. Open {url}/mission-control")
        print("No second server or worker was started.")
        return 0
    if state == "occupied":
        print(f"Port {port} is occupied, but the CareerOS page did not pass its readiness check.")
        print("Stop the older server in its terminal with Ctrl+C, then run this launcher again.")
        return 1
    print(f"Starting CareerOS: {url}/mission-control", flush=True)
    # Fixed interpreter and module; no command or arguments from web content.
    os.execv(sys.executable, [sys.executable, "-m", "careeros", "serve"])  # noqa: S606
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
