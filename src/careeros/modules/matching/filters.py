"""Hard filters. Each returns pass, fail or unknown with a reason and evidence.

Unknown is a first-class result: it is surfaced for review, never silently
turned into a pass or a fail.
"""

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from careeros.modules.matching.inputs import JobInput, LaneInput, ProfileInput
from careeros.modules.matching.seniority import SeniorityGuess
from careeros.modules.matching.text import contains_term, excerpt

Decision = Literal["pass", "fail", "unknown"]


@dataclass(frozen=True)
class FilterResult:
    name: str
    decision: Decision
    reason: str
    evidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------- employment type and exclusions ----------


_EMPLOYMENT_PHRASES: dict[str, re.Pattern[str]] = {
    "full_time": re.compile(
        r"\b(?:this is an?\s+|is an?\s+|position type:?\s*|employment type:?\s*)?"
        r"full[- ]time(?![- ]equivalent)\b(?:\s+(?:role|position|job|opportunity|employee|"
        r"permanent|salaried|exempt|w-?2))?"
    ),
    "part_time": re.compile(r"\bpart[- ]time\s+(?:role|position|job|opportunity)\b"),
    "contract": re.compile(
        r"\b(?:this is an?\s+)?(?:\d+[- ]month\s+)?contract(?:or)?\s+(?:role|position|"
        r"assignment|engagement|opportunity)\b|\bcontract[- ]to[- ]hire\b"
    ),
    "internship": re.compile(r"\b(?:summer\s+)?internship\s+(?:role|position|program)\b"),
    "temporary": re.compile(r"\btemporary\s+(?:role|position|assignment)\b"),
}


def _employment_from_description(text: str) -> tuple[set[str], dict[str, re.Match[str]]]:
    low = text.lower()
    found: dict[str, re.Match[str]] = {}
    for kind, pattern in _EMPLOYMENT_PHRASES.items():
        m = pattern.search(low)
        if m:
            found[kind] = m
    return set(found), found


def employment_filter(job: JobInput, lane: LaneInput) -> FilterResult:
    allowed = ", ".join(t.replace("_", " ") for t in lane.employment_types)
    if job.employment_type is not None:
        label = job.employment_type.replace("_", " ")
        if job.employment_type in lane.employment_types:
            return FilterResult("employment_type", "pass", f"Source states {label}.")
        return FilterResult(
            "employment_type", "fail", f"Source states {label}; lane wants {allowed}."
        )
    # The source field is empty: look for an explicit statement in the posting text.
    kinds, matches = _employment_from_description(job.description)
    if not kinds:
        return FilterResult(
            "employment_type",
            "unknown",
            f"Neither the source nor the description states the employment type "
            f"(lane wants {allowed}).",
        )
    quote = excerpt(job.description, next(iter(matches.values())), 70)
    if kinds <= set(lane.employment_types):
        found = ", ".join(sorted(k.replace("_", " ") for k in kinds))
        return FilterResult(
            "employment_type", "pass", f"Description explicitly says {found}.", quote
        )
    found = ", ".join(sorted(k.replace("_", " ") for k in kinds))
    return FilterResult(
        "employment_type",
        "unknown",
        f"Description mentions {found}; lane wants {allowed}. Check the posting.",
        quote,
    )


def excluded_terms_filter(job: JobInput, lane: LaneInput) -> FilterResult:
    hits = [t for t in lane.excluded_terms if contains_term(job.title, t)]
    if hits:
        return FilterResult(
            "excluded_terms", "fail", f"Title contains excluded term '{hits[0]}'.", job.title
        )
    return FilterResult("excluded_terms", "pass", "No excluded terms in the title.")


def title_exclude_filter(job: JobInput, lane: LaneInput) -> FilterResult:
    hits = [t for t in lane.title_exclude if contains_term(job.title, t)]
    if hits:
        return FilterResult(
            "title_exclusions",
            "fail",
            f"Title contains '{hits[0]}', which this lane excludes.",
            job.title,
        )
    return FilterResult("title_exclusions", "pass", "Title has no lane exclusions.")


# ---------- seniority ----------


def seniority_filter(guess: SeniorityGuess, lane: LaneInput) -> FilterResult:
    allowed = ", ".join(lane.seniority_allowed) or "none"
    if guess.level is None:
        return FilterResult("seniority", "unknown", f"Couldn't tell seniority ({guess.rationale}).")
    if guess.level in lane.seniority_allowed:
        return FilterResult(
            "seniority", "pass", f"Looks {guess.level} ({guess.rationale}); lane allows {allowed}."
        )
    if guess.confidence == "high":
        return FilterResult(
            "seniority", "fail", f"Looks {guess.level} ({guess.rationale}); lane allows {allowed}."
        )
    return FilterResult(
        "seniority",
        "unknown",
        f"Possibly {guess.level} ({guess.rationale}, {guess.confidence} confidence); "
        f"lane allows {allowed}. Check the posting.",
    )


# ---------- location ----------

_US_STATES = frozenset(
    [
        "al",
        "ak",
        "az",
        "ar",
        "ca",
        "co",
        "ct",
        "de",
        "fl",
        "ga",
        "hi",
        "id",
        "il",
        "in",
        "ia",
        "ks",
        "ky",
        "la",
        "me",
        "md",
        "ma",
        "mi",
        "mn",
        "ms",
        "mo",
        "mt",
        "ne",
        "nv",
        "nh",
        "nj",
        "nm",
        "ny",
        "nc",
        "nd",
        "oh",
        "ok",
        "or",
        "pa",
        "ri",
        "sc",
        "sd",
        "tn",
        "tx",
        "ut",
        "vt",
        "va",
        "wa",
        "wv",
        "wi",
        "wy",
        "dc",
    ]
)
_US_NAMES = (
    "united states",
    "usa",
    "u.s.",
    "us",
    "alabama",
    "alaska",
    "arizona",
    "arkansas",
    "california",
    "colorado",
    "connecticut",
    "delaware",
    "florida",
    "georgia",
    "hawaii",
    "idaho",
    "illinois",
    "indiana",
    "iowa",
    "kansas",
    "kentucky",
    "louisiana",
    "maine",
    "maryland",
    "massachusetts",
    "michigan",
    "minnesota",
    "mississippi",
    "missouri",
    "montana",
    "nebraska",
    "nevada",
    "new hampshire",
    "new jersey",
    "new mexico",
    "new york",
    "north carolina",
    "north dakota",
    "ohio",
    "oklahoma",
    "oregon",
    "pennsylvania",
    "rhode island",
    "south carolina",
    "south dakota",
    "tennessee",
    "texas",
    "utah",
    "vermont",
    "virginia",
    "washington",
    "west virginia",
    "wisconsin",
    "wyoming",
)
_ALIASES = {
    "nyc": "new york",
    "sf": "san francisco",
    "bay area": "san francisco",
    "la": "los angeles",
    "dc": "washington",
    "boston area": "boston",
}
_STATE_ABBR = re.compile(r",\s*([A-Z]{2})\b")


def looks_us(location: str) -> bool:
    if any(m.group(1).lower() in _US_STATES for m in _STATE_ABBR.finditer(location)):
        return True
    low = location.lower()
    return any(contains_term(low, name) for name in _US_NAMES)


_NON_US = (
    "canada",
    "toronto",
    "vancouver",
    "montreal",
    "ontario",
    "mexico",
    "cdmx",
    "brazil",
    "sao paulo",
    "argentina",
    "colombia",
    "chile",
    "united kingdom",
    "uk",
    "england",
    "london",
    "ireland",
    "dublin",
    "germany",
    "berlin",
    "munich",
    "france",
    "paris",
    "netherlands",
    "amsterdam",
    "spain",
    "madrid",
    "barcelona",
    "portugal",
    "lisbon",
    "poland",
    "warsaw",
    "sweden",
    "stockholm",
    "switzerland",
    "zurich",
    "italy",
    "milan",
    "india",
    "bengaluru",
    "bangalore",
    "hyderabad",
    "mumbai",
    "pune",
    "delhi",
    "singapore",
    "japan",
    "tokyo",
    "china",
    "shanghai",
    "hong kong",
    "australia",
    "sydney",
    "melbourne",
    "new zealand",
    "philippines",
    "manila",
    "south korea",
    "seoul",
    "israel",
    "tel aviv",
    "uae",
    "dubai",
    "emea",
    "apac",
    "latam",
)


def looks_non_us(location: str) -> bool:
    """True only when the location names a non-US place and no US place at all."""
    if looks_us(location):
        return False
    low = location.lower()
    return any(contains_term(low, name) for name in _NON_US)


def _place_keys(place: str) -> set[str]:
    low = place.lower().strip()
    city = low.split(",")[0].strip()
    keys = {low, city, _ALIASES.get(city, city), _ALIASES.get(low, low)}
    return {k for k in keys if k}


def _matches_place(location: str, places: tuple[str, ...]) -> str | None:
    low = location.lower()
    for place in places:
        for key in _place_keys(place):
            if contains_term(low, key):
                return place
    return None


def location_filter(job: JobInput, lane: LaneInput, profile: ProfileInput) -> FilterResult:
    loc = job.location_text or ""
    if loc and looks_non_us(loc):
        return FilterResult("location", "fail", "Location is outside the US.", loc)
    if job.workplace_type == "remote" or (loc and contains_term(loc, "remote")):
        if lane.remote_ok:
            us_note = (
                ""
                if not loc or looks_us(loc) or loc.strip().lower() == "remote"
                else " Check which countries remote covers."
            )
            return FilterResult(
                "location", "pass", f"Remote role; lane accepts remote.{us_note}", loc or None
            )
        return FilterResult(
            "location", "fail", "Remote role; lane is set to not accept remote.", loc or None
        )
    if not loc:
        return FilterResult("location", "unknown", "Source doesn't state a location.")
    places = (
        tuple(p for p in ((profile.current_location,) if profile.current_location else ()))
        + profile.relocation_locations
        + lane.preferred_locations
    )
    hit = _matches_place(loc, places)
    if hit:
        return FilterResult("location", "pass", f"Matches your location preference '{hit}'.", loc)
    if profile.open_to_relocation is True:
        if looks_us(loc):
            return FilterResult(
                "location", "pass", "US location and you're open to relocating.", loc
            )
        return FilterResult(
            "location", "unknown", "Open to relocation, but this may be outside the US.", loc
        )
    if profile.open_to_relocation is False:
        return FilterResult(
            "location", "fail", "Not in your locations and you're not open to relocating.", loc
        )
    return FilterResult(
        "location", "unknown", "Not in your listed locations; relocation preference not set.", loc
    )


# ---------- work authorization ----------

_RESTRICT = [
    re.compile(p)
    for p in (
        r"(?:will not|won't|do not|does not|don't|doesn't|cannot|can't|unable to|not able to|"
        r"are not able to|is not able to)\s+(?:currently\s+)?(?:provide\s+|offer\s+|support\s+)?"
        r"(?:visa\s+|immigration\s+|employment\s+)?sponsor",
        r"\bno\s+(?:visa\s+|immigration\s+)?sponsorship",
        r"sponsorship\s+(?:is\s+)?(?:not|un)\s*(?:available|provided|offered|possible)",
        r"without\s+(?:the\s+need\s+for\s+)?(?:current\s+or\s+future\s+|future\s+)?"
        r"(?:visa\s+|employment\s+)?sponsorship",
        r"not\s+eligible\s+for\s+(?:visa\s+)?sponsorship",
    )
]
_CITIZEN = [
    re.compile(p)
    for p in (
        r"must\s+be\s+(?:a\s+)?(?:u\.?s\.?|united states)\s+citizen",
        r"(?:u\.?s\.?|united states)\s+citizenship\s+(?:is\s+)?required",
        r"(?:active|current|ability to obtain)?\s*(?:top\s+)?(?:secret|security)\s+clearance",
        r"green\s+card\s+holders?\s+only",
    )
]
_SPONSOR_OK = [
    re.compile(p)
    for p in (
        r"(?:we|will|can|are able to|is able to)\s+(?:provide\s+|offer\s+)?(?:visa\s+)?"
        r"sponsor(?!ship\s+is\s+not)",
        r"sponsorship\s+(?:is\s+)?(?:available|provided|offered)",
    )
]


def _first(patterns: list[re.Pattern[str]], text: str) -> re.Match[str] | None:
    for p in patterns:
        m = p.search(text)
        if m:
            return m
    return None


def work_authorization_filter(job: JobInput, profile: ProfileInput) -> FilterResult:
    """Reads only what the posting says. Never claims eligibility as fact."""
    text = job.description
    low = text.lower()
    need = profile.needs_sponsorship
    restrict = _first(_RESTRICT, low)
    citizen = _first(_CITIZEN, low)
    if restrict or citizen:
        m = restrict or citizen
        assert m is not None
        quote = excerpt(text, m)
        kind = "won't sponsor visas" if restrict else "requires US citizenship or clearance"
        if need == "yes":
            return FilterResult(
                "work_authorization",
                "fail",
                f"Posting says it {kind}; your confirmed status needs sponsorship.",
                quote,
            )
        if restrict and need == "no":
            return FilterResult(
                "work_authorization",
                "pass",
                "Posting won't sponsor; your confirmed status doesn't need it.",
                quote,
            )
        return FilterResult(
            "work_authorization",
            "unknown",
            f"Posting {kind}. Review against your own status.",
            quote,
        )
    if need == "no":
        return FilterResult(
            "work_authorization",
            "pass",
            "Posting doesn't mention sponsorship, and your confirmed status doesn't need it.",
        )
    ok = _first(_SPONSOR_OK, low)
    if ok:
        return FilterResult(
            "work_authorization",
            "pass",
            "Posting mentions sponsorship is available. Confirm with the employer.",
            excerpt(text, ok),
        )
    return FilterResult(
        "work_authorization",
        "unknown",
        "Posting doesn't state a sponsorship policy. Unknown, not assumed.",
    )


# ---------- stale / closed ----------


def status_filter(job: JobInput) -> FilterResult:
    if job.status == "closed":
        return FilterResult("posting_status", "fail", "The source no longer lists this job.")
    return FilterResult("posting_status", "pass", "Still listed by the source.")


def combine(results: list[FilterResult]) -> Decision:
    decisions = {r.decision for r in results}
    if "fail" in decisions:
        return "fail"
    if "unknown" in decisions:
        return "unknown"
    return "pass"
