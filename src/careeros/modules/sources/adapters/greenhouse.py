"""Greenhouse public Job Board API: boards-api.greenhouse.io/v1/boards/{token}/jobs."""

from typing import Any

from careeros.modules.sources.adapters.base import (
    InvalidPayloadError,
    parse_iso,
    require_list,
    str_or_none,
    validate_token,
)
from careeros.modules.sources.http import Fetcher
from careeros.modules.sources.schemas import NormalizedJob
from careeros.modules.sources.text import html_to_text


class GreenhouseAdapter:
    source_type = "greenhouse"

    def list_url(self, token: str) -> str:
        return f"https://boards-api.greenhouse.io/v1/boards/{validate_token(token)}/jobs"

    def fetch_raw(
        self, fetcher: Fetcher, token: str, min_interval: float
    ) -> tuple[list[dict[str, Any]], int]:
        payload, status = fetcher.get_json(
            self.list_url(token), params={"content": "true"}, min_interval=min_interval
        )
        return require_list(payload, "jobs"), status

    def normalize(self, raw: dict[str, Any], company_name: str) -> NormalizedJob:
        if "id" not in raw or "title" not in raw or "absolute_url" not in raw:
            raise InvalidPayloadError("Greenhouse job missing id, title or absolute_url")
        location = raw.get("location")
        location_text = str_or_none(location.get("name")) if isinstance(location, dict) else None
        departments = raw.get("departments")
        department = None
        if isinstance(departments, list) and departments and isinstance(departments[0], dict):
            department = str_or_none(departments[0].get("name"), 200)
        workplace = (
            "remote" if location_text and location_text.strip().lower() == "remote" else None
        )
        return NormalizedJob(
            external_id=str(raw["id"]),
            source_url=str(raw["absolute_url"]),
            title=str(raw["title"]).strip(),
            company_name=str_or_none(raw.get("company_name"), 200) or company_name,
            location_text=location_text,
            workplace_type=workplace,
            employment_type=None,  # not exposed by the list API; unknown, not assumed
            department=department,
            description_text=html_to_text(raw.get("content")),
            posted_at=parse_iso(raw.get("first_published")) or parse_iso(raw.get("updated_at")),
            raw=raw,
        )
