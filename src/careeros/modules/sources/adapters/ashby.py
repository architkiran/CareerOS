"""Ashby public Job Posting API: api.ashbyhq.com/posting-api/job-board/{board}."""

from typing import Any

from careeros.modules.sources.adapters.base import (
    InvalidPayloadError,
    employment_from_text,
    parse_iso,
    require_list,
    str_or_none,
    validate_token,
    workplace_from_text,
)
from careeros.modules.sources.http import Fetcher
from careeros.modules.sources.schemas import NormalizedJob
from careeros.modules.sources.text import html_to_text

_INTERVALS = {"1 YEAR": "year", "1 MONTH": "month", "1 HOUR": "hour", "1 WEEK": "week"}


class AshbyAdapter:
    source_type = "ashby"

    def list_url(self, token: str) -> str:
        return f"https://api.ashbyhq.com/posting-api/job-board/{validate_token(token)}"

    def fetch_raw(
        self, fetcher: Fetcher, token: str, min_interval: float
    ) -> tuple[list[dict[str, Any]], int]:
        payload, status = fetcher.get_json(
            self.list_url(token), params={"includeCompensation": "true"}, min_interval=min_interval
        )
        # Unlisted postings are for direct-link access only; respect that.
        return [j for j in require_list(payload, "jobs") if j.get("isListed", True)], status

    def normalize(self, raw: dict[str, Any], company_name: str) -> NormalizedJob:
        url = raw.get("jobUrl") or raw.get("applyUrl")
        if not raw.get("id") or not raw.get("title") or not url:
            raise InvalidPayloadError("Ashby job missing id, title or jobUrl")
        workplace = workplace_from_text(raw.get("workplaceType"))
        if workplace is None and raw.get("isRemote") is True:
            workplace = "remote"
        smin, smax, cur, interval = _salary(raw.get("compensation"))
        return NormalizedJob(
            external_id=str(raw["id"]),
            source_url=str(url),
            title=str(raw["title"]).strip(),
            company_name=company_name,
            location_text=str_or_none(raw.get("location")),
            workplace_type=workplace,
            employment_type=employment_from_text(raw.get("employmentType")),
            department=str_or_none(raw.get("department") or raw.get("team"), 200),
            description_text=raw.get("descriptionPlain")
            or html_to_text(raw.get("descriptionHtml")),
            salary_min=smin,
            salary_max=smax,
            salary_currency=cur,
            salary_interval=interval,
            posted_at=parse_iso(raw.get("publishedAt")),
            publication_kind="last_publication",
            raw=raw,
        )


def _salary(comp: Any) -> tuple[int | None, int | None, str | None, str | None]:
    """Use only an explicit Salary component. Equity or bonus ranges are ignored."""
    if not isinstance(comp, dict):
        return None, None, None, None
    for c in comp.get("summaryComponents") or []:
        if isinstance(c, dict) and c.get("compensationType") == "Salary":
            lo, hi = c.get("minValue"), c.get("maxValue")
            return (
                int(lo) if isinstance(lo, int | float) and lo >= 0 else None,
                int(hi) if isinstance(hi, int | float) and hi >= 0 else None,
                str_or_none(c.get("currencyCode"), 10),
                _INTERVALS.get(str(c.get("interval")), str_or_none(c.get("interval"), 20)),
            )
    return None, None, None, None
