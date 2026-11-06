"""Documented public Posting API. US feed scope is explicit; capped snapshots fail closed."""

from typing import Any

from careeros.modules.sources.adapters.base import (
    InvalidPayloadError,
    employment_from_text,
    parse_iso,
    require_list,
    str_or_none,
    validate_token,
)
from careeros.modules.sources.http import Fetcher
from careeros.modules.sources.schemas import NormalizedJob
from careeros.modules.sources.text import html_to_text

MAX_POSTINGS = 200


class SmartRecruitersAdapter:
    source_type = "smartrecruiters"

    def list_url(self, token: str) -> str:
        return f"https://api.smartrecruiters.com/v1/companies/{validate_token(token)}/postings"

    def fetch_raw(
        self, fetcher: Fetcher, token: str, min_interval: float
    ) -> tuple[list[dict[str, Any]], int]:
        base = self.list_url(token)
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload, status = fetcher.get_json(
                base,
                params={"country": "us", "limit": 100, "offset": offset},
                min_interval=min_interval,
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("totalFound"), int):
                raise InvalidPayloadError("SmartRecruiters snapshot has no valid total")
            total = payload["totalFound"]
            if total < 0 or total > MAX_POSTINGS:
                raise InvalidPayloadError(
                    "US board exceeds the bounded posting limit; existing jobs were preserved"
                )
            batch = require_list(payload, "content")
            if not batch and offset < total:
                raise InvalidPayloadError(
                    "Incomplete SmartRecruiters pagination; existing jobs were preserved"
                )
            items.extend(batch)
            if len(items) > MAX_POSTINGS:
                raise InvalidPayloadError("SmartRecruiters snapshot exceeded its cap")
            offset += len(batch)
            if offset >= total:
                break
        if len(items) != total:
            raise InvalidPayloadError(
                "Snapshot count changed during pagination; existing jobs were preserved"
            )
        if len({str(item.get("id")) for item in items}) != len(items):
            raise InvalidPayloadError("Duplicate posting IDs in paginated snapshot")
        details = []
        for item in items:
            posting_id = str(item.get("id", ""))
            try:
                validate_token(posting_id)
            except ValueError as exc:
                raise InvalidPayloadError("Invalid posting ID in snapshot") from exc
            # Never follow untrusted ref/apply URLs for network requests.
            raw, status = fetcher.get_json(base + "/" + posting_id, min_interval=min_interval)
            if (
                not isinstance(raw, dict)
                or str(raw.get("id")) != posting_id
                or raw.get("active") is False
            ):
                raise InvalidPayloadError(
                    "Posting detail changed during refresh; retry the complete snapshot"
                )
            details.append(raw)
        return details, status

    def normalize(self, raw: dict[str, Any], company_name: str) -> NormalizedJob:
        if not raw.get("id") or not raw.get("name") or not raw.get("applyUrl"):
            raise InvalidPayloadError("SmartRecruiters posting is missing id, title or URL")
        location = raw.get("location") or {}
        sections = (raw.get("jobAd") or {}).get("sections") or {}
        if not isinstance(location, dict) or not isinstance(sections, dict):
            raise InvalidPayloadError("Invalid posting location or sections")
        text = "\n\n".join(
            html_to_text(section.get("text"))
            for section in sections.values()
            if isinstance(section, dict)
        )
        if not text.strip():
            raise InvalidPayloadError("Posting detail has no description")
        employment = raw.get("typeOfEmployment") or {}
        department = raw.get("department") or {}
        return NormalizedJob(
            external_id=str(raw["id"]),
            source_url=str(raw["applyUrl"]),
            title=str(raw["name"]),
            company_name=company_name,
            location_text=", ".join(
                str(location[k]) for k in ("city", "region", "country") if location.get(k)
            ),
            workplace_type="remote" if location.get("remote") is True else None,
            employment_type=employment_from_text(employment.get("label")),
            department=str_or_none(department.get("label"), 200),
            description_text=text,
            posted_at=parse_iso(raw.get("releasedDate")),
            raw=raw,
        )
