"""Workday career sites, read through the same public CXS JSON the careers page itself calls.

    POST https://{tenant}.{shard}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
    GET  https://{tenant}.{shard}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{externalPath}

Board token: ``tenant.shard.site`` (for example ``statestreet.wd1.Global``).

Politeness and honesty rules built in:
- robots.txt for the host is read first; a disallow stops the source (SourceBlockedError).
- The list endpoint is queried by a few early-career search terms and bounded pages, so a run
  is a *partial* snapshot. Absence never closes a job (see PARTIAL_SNAPSHOT_TYPES).
- Posting text needs one detail request per job, so details are fetched only for titles that
  pass a cheap prefilter, only once per posting, and capped per run.
"""

import re
from typing import Any
from urllib import robotparser

from careeros.modules.sources.adapters.base import (
    InvalidPayloadError,
    employment_from_text,
    parse_iso,
    str_or_none,
    validate_token,
    workplace_from_text,
)
from careeros.modules.sources.http import (
    USER_AGENT,
    Fetcher,
    FetchError,
    SourceBlockedError,
    SourceNotFoundError,
)
from careeros.modules.sources.schemas import NormalizedJob
from careeros.modules.sources.text import html_to_text

SEARCH_TERMS = ("analyst", "data", "associate")
PAGE_SIZE = 20  # Workday rejects larger pages
MAX_PAGES_PER_TERM = 3
MAX_DETAILS_PER_RUN = 20

# Titles that can never satisfy the candidate's hard rules; skipping them saves detail requests.
_SKIP_TITLE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|manager|director|vp|vice president|head of|"
    r"intern|internship|co-?op|architect|chief|president|counsel|attorney|nurse|physician|"
    r"technician|driver|teller|cashier)\b",
    re.IGNORECASE,
)
_POSTED_DAYS = re.compile(r"(\d+)\+?\s+day", re.IGNORECASE)


def parse_token(token: str) -> tuple[str, str, str]:
    validate_token(token)
    parts = token.split(".", 2)
    if len(parts) != 3 or not re.fullmatch(r"wd\d{1,3}", parts[1]) or not all(parts):
        raise ValueError("Workday token must be tenant.wdN.site, e.g. statestreet.wd1.Global")
    return parts[0], parts[1], parts[2]


def posted_days_ago(text: Any) -> int:
    """'Posted Today' → 0, 'Posted 3 Days Ago' → 3, 'Posted 30+ Days Ago' → 30; unknown → 999."""
    if not isinstance(text, str):
        return 999
    low = text.lower()
    if "today" in low:
        return 0
    if "yesterday" in low:
        return 1
    m = _POSTED_DAYS.search(low)
    return int(m.group(1)) if m else 999


def worth_detail(title: str) -> bool:
    return not _SKIP_TITLE.search(title)


class WorkdayAdapter:
    source_type = "workday"

    def __init__(self) -> None:
        self._robots: dict[str, bool] = {}

    def _base(self, token: str) -> tuple[str, str, str]:
        tenant, shard, site = parse_token(token)
        host = f"https://{tenant}.{shard}.myworkdayjobs.com"
        return host, f"{host}/wday/cxs/{tenant}/{site}", f"{host}/en-US/{site}"

    def list_url(self, token: str) -> str:
        return self._base(token)[1] + "/jobs"

    def _allowed(self, fetcher: Fetcher, host: str, path: str, min_interval: float) -> bool:
        if host not in self._robots:
            try:
                text, _ = fetcher.get_text(host + "/robots.txt", min_interval=min_interval)
            except SourceNotFoundError:
                self._robots[host] = True
            except FetchError:
                # robots.txt unreachable: do not guess permission in either direction.
                raise
            else:
                parser = robotparser.RobotFileParser()
                parser.parse(text.splitlines())
                self._robots[host] = parser.can_fetch(USER_AGENT, host + path)
        return self._robots[host]

    def fetch_raw(
        self, fetcher: Fetcher, token: str, min_interval: float
    ) -> tuple[list[dict[str, Any]], int]:
        return self.fetch_raw_incremental(fetcher, token, min_interval, set())

    def fetch_raw_incremental(
        self, fetcher: Fetcher, token: str, min_interval: float, known: set[str]
    ) -> tuple[list[dict[str, Any]], int]:
        host, api, public = self._base(token)
        tenant, _, site = parse_token(token)
        if not self._allowed(fetcher, host, f"/wday/cxs/{tenant}/{site}/jobs", min_interval):
            raise SourceBlockedError("robots.txt disallows this job search path", 403)
        listed: dict[str, dict[str, Any]] = {}
        status = 200
        for term in SEARCH_TERMS:
            for page in range(MAX_PAGES_PER_TERM):
                payload, status = fetcher.post_json(
                    api + "/jobs",
                    {
                        "appliedFacets": {},
                        "limit": PAGE_SIZE,
                        "offset": page * PAGE_SIZE,
                        "searchText": term,
                    },
                    min_interval=min_interval,
                )
                if not isinstance(payload, dict) or not isinstance(
                    payload.get("jobPostings"), list
                ):
                    raise InvalidPayloadError("Workday search response missing jobPostings")
                batch = [p for p in payload["jobPostings"] if isinstance(p, dict)]
                for item in batch:
                    path = item.get("externalPath")
                    if isinstance(path, str) and path.startswith("/"):
                        listed.setdefault(path, item)
                total = payload.get("total")
                if len(batch) < PAGE_SIZE or (
                    isinstance(total, int) and (page + 1) * PAGE_SIZE >= total
                ):
                    break
        out: list[dict[str, Any]] = []
        fresh: list[tuple[int, str, dict[str, Any]]] = []
        for path, item in listed.items():
            if path in known:
                out.append({"id": path, "_seen_only": True})
            elif worth_detail(str(item.get("title") or "")):
                fresh.append((posted_days_ago(item.get("postedOn")), path, item))
        fresh.sort(key=lambda entry: entry[0])
        for _, path, item in fresh[:MAX_DETAILS_PER_RUN]:
            try:
                detail, status = fetcher.get_json(api + path, min_interval=min_interval)
            except SourceNotFoundError:
                continue  # removed between list and detail
            info = detail.get("jobPostingInfo") if isinstance(detail, dict) else None
            if not isinstance(info, dict):
                continue
            out.append({"id": path, "list": item, "detail": info, "public_base": public})
        return out, status

    def normalize(self, raw: dict[str, Any], company_name: str) -> NormalizedJob:
        info, path = raw.get("detail"), raw.get("id")
        if not isinstance(info, dict) or not isinstance(path, str) or not info.get("title"):
            raise InvalidPayloadError("Workday job missing detail or title")
        url = str_or_none(info.get("externalUrl"), 1000) or f"{raw.get('public_base')}{path}"
        places = [info.get("location"), *(info.get("additionalLocations") or [])]
        location = "; ".join(p.strip() for p in places if isinstance(p, str) and p.strip())
        country = info.get("country")
        country_name = country.get("descriptor") if isinstance(country, dict) else None
        if isinstance(country_name, str) and country_name.lower() not in location.lower():
            location = f"{location} ({country_name})" if location else country_name
        return NormalizedJob(
            external_id=path[:200],
            source_url=url,
            title=str(info["title"]).strip(),
            company_name=company_name,
            location_text=str_or_none(location),
            workplace_type=workplace_from_text(info.get("remoteType")),
            employment_type=employment_from_text(info.get("timeType")),
            description_text=html_to_text(info.get("jobDescription")),
            # startDate is the date this posting went live on the careers site.
            posted_at=parse_iso(info.get("startDate")),
            publication_kind="provider_reported",
            raw={"list": raw.get("list"), "detail": info},
        )
