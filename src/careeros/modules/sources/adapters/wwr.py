"""WWR's explicitly reusable public RSS; bounded, attributed and windowed."""

from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit
from xml.etree.ElementTree import ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

from careeros.modules.sources.adapters.base import InvalidPayloadError, employment_from_text
from careeros.modules.sources.http import Fetcher
from careeros.modules.sources.schemas import NormalizedJob
from careeros.modules.sources.text import html_to_text


class WWRAdapter:
    source_type = "wwr"

    def list_url(self, token: str) -> str:
        if token != "all":  # noqa: S105 — public feed identifier, not a secret
            raise InvalidPayloadError("Use the documented all-jobs public RSS.")
        return "https://weworkremotely.com/remote-jobs.rss"

    def fetch_raw(
        self, fetcher: Fetcher, token: str, min_interval: float
    ) -> tuple[list[dict[str, Any]], int]:
        xml, status = fetcher.get_text(self.list_url(token), min_interval=min_interval)
        try:
            root = fromstring(xml)
        except (ParseError, DefusedXmlException) as exc:
            raise InvalidPayloadError("Invalid or unsafe RSS payload") from exc
        items = root.findall("./channel/item")
        if len(items) > 500:
            raise InvalidPayloadError("RSS exceeds safe listing limit")
        return [{child.tag: child.text or "" for child in item} for item in items], status

    def normalize(self, raw: dict[str, Any], company_name: str) -> NormalizedJob:
        company, _, title = html_to_text(raw.get("title")).partition(": ")
        url = raw.get("link")
        if (
            not title
            or not isinstance(url, str)
            or urlsplit(url).hostname != "weworkremotely.com"
            or not url.startswith("https://")
        ):
            raise InvalidPayloadError("RSS listing needs a title, employer and original WWR URL")
        posted = None
        try:
            posted = parsedate_to_datetime(raw.get("pubDate", ""))
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            pass
        return NormalizedJob(
            external_id=str(raw.get("guid") or url),
            source_url=url,
            title=title,
            company_name=company,
            location_text=", ".join(
                str(raw[k]) for k in ("region", "country", "state") if raw.get(k)
            )
            or None,
            workplace_type="remote",
            employment_type=employment_from_text(raw.get("type")),
            description_text=html_to_text(raw.get("description")),
            posted_at=posted,
            raw=raw,
        )
