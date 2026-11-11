"""Community-maintained new-graduate listing feeds published as JSON on GitHub.

These are third-party lists. They widen discovery (each entry links to the employer's own
posting) but they are never treated as the employer's word: no posting text, and their
sponsorship flag is third-party (Level C at best). Official ATS sources verify the role.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from careeros.common.clock import utcnow
from careeros.modules.sources.adapters.base import InvalidPayloadError, str_or_none
from careeros.modules.sources.http import Fetcher
from careeros.modules.sources.schemas import NormalizedJob

FEEDS = {
    "simplify-newgrad": (
        "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/"
        ".github/scripts/listings.json"
    ),
}
MAX_AGE_DAYS = 45
_TRACKING = ("utm_", "ref", "source", "src", "gh_src")


def clean_url(url: str) -> str:
    parts = urlsplit(url)
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not any(k.lower() == t or k.lower().startswith("utm_") for t in _TRACKING)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


class CommunityFeedAdapter:
    source_type = "community"

    def list_url(self, token: str) -> str:
        if token not in FEEDS:
            raise ValueError(f"Unknown community feed {token!r}")
        return FEEDS[token]

    def fetch_raw(
        self, fetcher: Fetcher, token: str, min_interval: float
    ) -> tuple[list[dict[str, Any]], int]:
        payload, status = fetcher.get_json(self.list_url(token), min_interval=min_interval)
        if not isinstance(payload, list):
            raise InvalidPayloadError("Community feed is not a JSON list")
        cutoff = (utcnow() - timedelta(days=MAX_AGE_DAYS)).timestamp()
        items = [
            item
            for item in payload
            if isinstance(item, dict)
            and item.get("active") is True
            and item.get("is_visible", True)
            and isinstance(item.get("date_posted"), int | float)
            and item["date_posted"] >= cutoff
        ]
        return items, status

    def normalize(self, raw: dict[str, Any], company_name: str) -> NormalizedJob:
        for key in ("id", "title", "url", "company_name"):
            if not isinstance(raw.get(key), str) or not raw[key].strip():
                raise InvalidPayloadError(f"Community listing missing {key}")
        locations = [loc for loc in raw.get("locations") or [] if isinstance(loc, str)]
        return NormalizedJob(
            external_id=raw["id"][:200],
            source_url=clean_url(raw["url"].strip()),
            title=raw["title"].strip()[:300],
            company_name=raw["company_name"].strip()[:200],
            location_text=str_or_none("; ".join(locations)),
            description_text="",  # the feed carries no posting text; never invent one
            posted_at=datetime.fromtimestamp(raw["date_posted"], tz=UTC),
            publication_kind="provider_reported",
            raw={
                k: raw.get(k)
                for k in ("id", "source", "category", "sponsorship", "date_posted", "url")
            },
        )
