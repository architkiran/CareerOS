"""Documented free job-board APIs. Windowed feeds never establish job closure."""

import html
from typing import Any
from urllib.parse import urlsplit

from careeros.modules.sources.adapters.base import (
    InvalidPayloadError,
    employment_from_text,
    parse_iso,
    require_list,
    validate_token,
)
from careeros.modules.sources.http import Fetcher
from careeros.modules.sources.schemas import NormalizedJob
from careeros.modules.sources.text import html_to_text


def _board_url(value: object, host: str) -> str:
    if not isinstance(value, str):
        raise InvalidPayloadError("Posting has no original board URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in (host, "www." + host)
        or parsed.username
        or parsed.password
    ):
        raise InvalidPayloadError("Posting must retain its original board URL")
    return value


class RemotiveAdapter:
    source_type = "remotive"

    def list_url(self, token: str) -> str:
        validate_token(token)
        return "https://remotive.com/api/remote-jobs"

    def fetch_raw(
        self, fetcher: Fetcher, token: str, min_interval: float
    ) -> tuple[list[dict[str, Any]], int]:
        data, status = fetcher.get_json(self.list_url(token), min_interval=min_interval)
        return require_list(data, "jobs"), status

    def normalize(self, raw: dict[str, Any], company_name: str) -> NormalizedJob:
        if not raw.get("id") or not raw.get("title") or not raw.get("company_name"):
            raise InvalidPayloadError("Remotive posting is missing an ID, title or employer")
        return NormalizedJob(
            external_id=str(raw["id"]),
            source_url=_board_url(raw.get("url"), "remotive.com"),
            title=html.unescape(raw["title"]),
            company_name=html.unescape(raw["company_name"]),
            location_text=raw.get("candidate_required_location") or None,
            workplace_type="remote",
            employment_type=employment_from_text(raw.get("job_type")),
            description_text=html_to_text(raw.get("description")),
            posted_at=parse_iso(raw.get("publication_date")),
            raw=raw,
        )


class JobicyAdapter:
    source_type = "jobicy"

    def list_url(self, token: str) -> str:
        validate_token(token)
        return "https://jobicy.com/api/jobs"

    def fetch_raw(
        self, fetcher: Fetcher, token: str, min_interval: float
    ) -> tuple[list[dict[str, Any]], int]:
        params = {"count": 100, "geo": "usa"}
        items = []
        cursors = set()
        status = 0
        for _ in range(10):
            data, status = fetcher.get_json(
                self.list_url(token), params=params, min_interval=min_interval
            )
            if not isinstance(data, dict) or data.get("success") is False:
                raise InvalidPayloadError("Jobicy returned an unsuccessful response")
            items.extend(require_list(data, "jobs"))
            cursor = data.get("nextCursor")
            if cursor is None and not data.get("hasMore"):
                return items, status
            if not isinstance(cursor, str) or cursor in cursors or len(cursor) > 2000:
                raise InvalidPayloadError("Jobicy pagination did not complete safely")
            cursors.add(cursor)
            params = {**params, "cursor": cursor}
        raise InvalidPayloadError("Jobicy pagination reached its safe page limit")

    def normalize(self, raw: dict[str, Any], company_name: str) -> NormalizedJob:
        if not raw.get("id") or not raw.get("companyName") or not raw.get("jobTitle"):
            raise InvalidPayloadError("Jobicy posting is missing an ID, employer or title")
        types = raw.get("jobType") or []
        return NormalizedJob(
            external_id=str(raw["id"]),
            source_url=_board_url(raw.get("url"), "jobicy.com"),
            title=html.unescape(raw["jobTitle"]),
            company_name=html.unescape(raw["companyName"]),
            location_text=raw.get("jobGeo") or None,
            workplace_type="remote",
            employment_type=employment_from_text(
                types[0] if isinstance(types, list) and types else None
            ),
            description_text=html_to_text(raw.get("jobDescription")),
            posted_at=parse_iso(raw.get("pubDate")),
            raw=raw,
        )
