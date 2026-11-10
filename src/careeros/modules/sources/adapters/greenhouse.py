"""Greenhouse public Job Board API: boards-api.greenhouse.io/v1/boards/{token}/jobs."""

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
from careeros.modules.sources.schemas import EmploymentType, NormalizedJob
from careeros.modules.sources.text import html_to_text

EMPLOYMENT_FIELDS = ("Employment Type", "Time Type", "Employee Type", "Worker Type")
# Single, unambiguous ranges only. Multi-zone fields ("Zone A/B/C Salary Range") are skipped:
# without knowing which zone applies, picking one would be a guess.
SALARY_FIELDS = ("Pay Transparency Range", "Compensation Range (Job Posts)", "Pay Range")
FREQUENCY_FIELDS = ("Pay Frequency", "WD - Pay Rate Type")
_FREQUENCY = {
    "annual": "year",
    "annually": "year",
    "yearly": "year",
    "salary": "year",
    "salaried": "year",
    "hourly": "hour",
    "monthly": "month",
    "weekly": "week",
}


def _metadata(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in raw.get("metadata") or []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            out.setdefault(item["name"], item.get("value"))
    return out


def _money(value: Any) -> int | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return int(n) if n >= 0 else None


def metadata_employment(meta: dict[str, Any]) -> EmploymentType | None:
    for name in EMPLOYMENT_FIELDS:
        found = employment_from_text(meta.get(name))
        if found:
            return found
    return None


def metadata_salary(meta: dict[str, Any]) -> tuple[int | None, int | None, str | None, str | None]:
    for name in SALARY_FIELDS:
        value = meta.get(name)
        if not isinstance(value, dict):
            continue
        lo, hi = _money(value.get("min_value")), _money(value.get("max_value"))
        if lo is None and hi is None:
            continue
        currency = str_or_none(value.get("unit"), 10)
        interval = None
        for freq_name in FREQUENCY_FIELDS:
            freq = meta.get(freq_name)
            if isinstance(freq, str) and freq.strip().lower() in _FREQUENCY:
                interval = _FREQUENCY[freq.strip().lower()]
                break
        if interval is None:
            # Only amounts that can't be hourly or monthly count as yearly; otherwise unknown.
            interval = (
                "year" if min(v for v in (lo, hi) if v is not None) >= 20_000 else "unspecified"
            )
        return lo, hi, currency, interval
    return None, None, None, None


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
        items = require_list(payload, "jobs")
        total = (payload.get("meta") or {}).get("total") if isinstance(payload, dict) else None
        if isinstance(total, int) and total != len(items):
            raise InvalidPayloadError(
                "Incomplete Greenhouse snapshot; existing jobs were preserved"
            )
        return items, status

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
        meta = _metadata(raw)
        salary_min, salary_max, currency, interval = metadata_salary(meta)
        return NormalizedJob(
            external_id=str(raw["id"]),
            source_url=str(raw["absolute_url"]),
            title=str(raw["title"]).strip(),
            company_name=str_or_none(raw.get("company_name"), 200) or company_name,
            location_text=location_text,
            workplace_type=workplace,
            employment_type=metadata_employment(meta),  # only when the board states it
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=currency,
            salary_interval=interval,
            department=department,
            description_text=html_to_text(raw.get("content")),
            # An update timestamp is not evidence of publication time.
            posted_at=parse_iso(raw.get("first_published")),
            publication_kind="original",
            last_modified_at=parse_iso(raw.get("updated_at")),
            raw=raw,
        )
