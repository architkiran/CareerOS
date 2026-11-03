"""Polite HTTP fetching, kept separate from parsing and persistence.

- explicit connect/read timeouts
- bounded retries with exponential backoff and jitter (timeouts, 429, 5xx only)
- honours Retry-After, capped
- per-domain minimum interval between requests
- response size cap
- 403/429 surface as SourceBlockedError so callers can stop the source
"""

import json
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from careeros import __version__

logger = logging.getLogger(__name__)

USER_AGENT = f"CareerOS/{__version__} (personal job search; local, low volume)"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class FetchError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SourceBlockedError(FetchError):
    """403 or persistent 429: the source is refusing us. Do not retry harder."""


class SourceNotFoundError(FetchError):
    """404: board token is wrong or the board was removed."""


@dataclass
class FetchPolicy:
    timeout_seconds: float = 20.0
    max_attempts: int = 3
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 30.0
    max_retry_after_seconds: float = 60.0
    max_response_bytes: int = 15_000_000


@dataclass
class Fetcher:
    policy: FetchPolicy = field(default_factory=FetchPolicy)
    client: httpx.Client | None = None
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    _last_request: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = httpx.Client(
                timeout=httpx.Timeout(self.policy.timeout_seconds),
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                follow_redirects=True,
            )

    def close(self) -> None:
        if self.client is not None:
            self.client.close()

    def _respect_rate_limit(self, host: str, min_interval: float) -> None:
        last = self._last_request.get(host)
        if last is not None:
            wait = min_interval - (self.monotonic() - last)
            if wait > 0:
                self.sleep(wait)
        self._last_request[host] = self.monotonic()

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), self.policy.max_retry_after_seconds)
            except ValueError:
                pass
        base = self.policy.backoff_base_seconds * (2 ** (attempt - 1))
        jitter = random.uniform(0, base / 2)  # noqa: S311 (not crypto)
        return float(min(base + jitter, self.policy.backoff_max_seconds))

    def get_json(
        self, url: str, *, params: dict[str, Any] | None = None, min_interval: float = 2.0
    ) -> tuple[Any, int]:
        """GET a URL and decode JSON. Returns (payload, status_code)."""
        assert self.client is not None
        host = urlsplit(url).netloc
        last_error: FetchError | None = None
        for attempt in range(1, self.policy.max_attempts + 1):
            self._respect_rate_limit(host, min_interval)
            try:
                response = self.client.get(url, params=params)
            except httpx.TimeoutException:
                last_error = FetchError(f"Timed out after {self.policy.timeout_seconds}s")
                retry_after = None
            except httpx.HTTPError as exc:
                last_error = FetchError(f"Network error: {type(exc).__name__}")
                retry_after = None
            else:
                status = response.status_code
                if status == 403:
                    raise SourceBlockedError("Source returned 403 Forbidden", status)
                if status == 404:
                    raise SourceNotFoundError("Source returned 404 Not Found", status)
                if status in RETRYABLE_STATUS:
                    last_error = (
                        SourceBlockedError("Rate limited (429)", status)
                        if status == 429
                        else FetchError(f"Server error {status}", status)
                    )
                    retry_after = response.headers.get("Retry-After")
                elif status >= 400:
                    raise FetchError(f"Unexpected HTTP {status}", status)
                else:
                    if len(response.content) > self.policy.max_response_bytes:
                        raise FetchError("Response exceeded size limit", status)
                    try:
                        return response.json(), status
                    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                        raise FetchError("Response was not valid JSON", status) from exc
            if attempt < self.policy.max_attempts:
                delay = self._backoff(attempt, retry_after)
                logger.info(
                    "Retrying %s in %.1fs (attempt %d): %s", host, delay, attempt, last_error
                )
                self.sleep(delay)
        assert last_error is not None
        raise last_error
