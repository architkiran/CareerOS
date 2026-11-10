"""Lever public Postings API: api.lever.co/v0/postings/{site}?mode=json (paginated)."""

from typing import Any

from careeros.modules.sources.adapters.base import (
    InvalidPayloadError,
    employment_from_text,
    parse_epoch_ms,
    require_list,
    str_or_none,
    validate_token,
    workplace_from_text,
)
from careeros.modules.sources.http import Fetcher
from careeros.modules.sources.schemas import NormalizedJob
from careeros.modules.sources.text import html_to_text

PAGE_SIZE = 100
MAX_PAGES = 50


class LeverAdapter:
    source_type = "lever"

    def list_url(self, token: str) -> str:
        return f"https://api.lever.co/v0/postings/{validate_token(token)}"

    def fetch_raw(
        self, fetcher: Fetcher, token: str, min_interval: float
    ) -> tuple[list[dict[str, Any]], int]:
        items: list[dict[str, Any]] = []
        status = 0
        for page in range(MAX_PAGES):
            payload, status = fetcher.get_json(
                self.list_url(token),
                params={"mode": "json", "skip": page * PAGE_SIZE, "limit": PAGE_SIZE},
                min_interval=min_interval,
            )
            batch = require_list(payload, None)
            items.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
        else:
            raise InvalidPayloadError(
                "Lever pagination reached its safe cap; existing jobs were preserved"
            )
        return items, status

    def normalize(self, raw: dict[str, Any], company_name: str) -> NormalizedJob:
        if not raw.get("id") or not raw.get("text"):
            raise InvalidPayloadError("Lever posting missing id or text")
        url = raw.get("hostedUrl") or raw.get("applyUrl")
        if not url:
            raise InvalidPayloadError("Lever posting missing hostedUrl")
        cats_raw = raw.get("categories")
        cats: dict[str, Any] = cats_raw if isinstance(cats_raw, dict) else {}
        parts = [raw.get("descriptionPlain") or html_to_text(raw.get("description"))]
        for block in raw.get("lists") or []:
            if isinstance(block, dict):
                parts.append(f"{block.get('text', '')}\n{html_to_text(block.get('content'))}")
        parts.append(raw.get("additionalPlain") or html_to_text(raw.get("additional")))
        salary_raw = raw.get("salaryRange")
        salary: dict[str, Any] = salary_raw if isinstance(salary_raw, dict) else {}
        return NormalizedJob(
            external_id=str(raw["id"]),
            source_url=str(url),
            title=str(raw["text"]).strip(),
            company_name=company_name,
            location_text=str_or_none(cats.get("location")),
            workplace_type=workplace_from_text(raw.get("workplaceType")),
            employment_type=employment_from_text(cats.get("commitment")),
            department=str_or_none(cats.get("team") or cats.get("department"), 200),
            description_text="\n\n".join(p.strip() for p in parts if p and p.strip()),
            salary_min=_int(salary.get("min")),
            salary_max=_int(salary.get("max")),
            salary_currency=str_or_none(salary.get("currency"), 10),
            salary_interval=str_or_none(salary.get("interval"), 20),
            posted_at=parse_epoch_ms(raw.get("createdAt")),
            publication_kind="source_creation",
            raw=raw,
        )


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        return None
    return int(value)
