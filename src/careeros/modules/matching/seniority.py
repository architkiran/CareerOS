"""Seniority is inferred, never treated as fact: always returned with confidence and rationale."""

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

Confidence = Literal["high", "medium", "low"]

_TITLE_RULES: list[tuple[re.Pattern[str], str, Confidence, str]] = [
    (
        re.compile(r"\b(head of|director|vp|vice president|principal|staff)\b"),
        "lead",
        "high",
        "title says {m}",
    ),
    (re.compile(r"\b(lead|manager)\b"), "lead", "medium", "title says {m}"),
    (re.compile(r"\b(senior|sr)\b"), "senior", "high", "title says {m}"),
    (re.compile(r"\b(iii|iv)\b"), "senior", "medium", "title level {m}"),
    (
        re.compile(r"\b(junior|jr|entry level|entry-level|new grad|graduate|early career)\b"),
        "entry",
        "high",
        "title says {m}",
    ),
    (re.compile(r"\bii\b"), "mid", "medium", "title level {m}"),
    (re.compile(r"\bassociate\b"), "junior", "medium", "title says {m}"),
    (re.compile(r"\bi\b\s*$"), "entry", "medium", "title level {m}"),
]

_YEARS = re.compile(
    r"(?<![\d.])(\d{1,2})(?!\.\d)\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?years?(?:\s+of)?[^.\n]{0,40}?experience"
)


@dataclass(frozen=True)
class SeniorityGuess:
    level: str | None
    confidence: Confidence | None
    rationale: str
    min_years: int | None = None


def _level_for_years(years: int) -> str:
    if years <= 1:
        return "entry"
    if years <= 2:
        return "junior"
    if years <= 4:
        return "mid"
    if years <= 7:
        return "senior"
    return "lead"


_REQUIRED_HEADINGS = {
    "requirements",
    "qualifications",
    "minimum qualifications",
    "required qualifications",
    "what you need",
    "what youll need",
    "what you bring",
    "what youll bring",
    "about you",
    "who you are",
    "what were looking for",
}
_OPTIONAL_HEADINGS = {
    "preferred qualifications",
    "preferred",
    "nice to have",
    "bonus",
    "bonus points",
    "desired qualifications",
    "additional qualifications",
}
_OTHER_HEADINGS = {"responsibilities", "benefits", "compensation", "about us", "what youll do"}
_TENURE = re.compile(
    r"(?<![\d.])(\d{1,2})(?!\.\d)\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?years?\b"
)
_MINIMUM = re.compile(r"\b(?:at least|minimum(?: of)?|requires?|required|must have)\b")
_OPTIONAL = re.compile(r"\b(?:preferred|preferably|nice to have|bonus|optional)\b")


def _experience_requirements(description: str) -> tuple[list[int], list[int]]:
    required: list[int] = []
    mentioned = [int(m.group(1)) for m in _YEARS.finditer(description)]
    section = ""
    for raw in re.split(r"\n|;\s*", description):
        line = raw.strip().lower()
        prefix, separator, rest = line.partition(":")
        prefix_key = re.sub(r"[^a-z ]", "", prefix).strip()
        if separator and prefix_key in _REQUIRED_HEADINGS | _OPTIONAL_HEADINGS:
            section = "required" if prefix_key in _REQUIRED_HEADINGS else "optional"
            line = rest.strip()
            if not line:
                continue
        heading = re.sub(r"[^a-z ]", "", line).strip()
        if heading in _REQUIRED_HEADINGS:
            section = "required"
            continue
        if heading in _OPTIONAL_HEADINGS:
            section = "optional"
            continue
        if heading in _OTHER_HEADINGS or (line.endswith(":") and len(line) < 100):
            section = ""
            continue
        matches = list(_TENURE.finditer(line))
        # Degree/experience alternatives cannot be collapsed into the larger number.
        alternatives = (
            len(matches) > 1
            and " or " in line
            and bool(re.search(r"bachelor|master|ph\.?d|degree", line))
        )
        for match in matches:
            years = int(match.group(1))
            detail = line[match.end() :].split(".", 1)[0][:100].strip()
            work = bool(re.search(r"\bexperience\b|\bworking\b|\bmanaging\b", detail)) or bool(
                re.match(r"(?:of\s+)?(?:in|as)\b", detail)
            )
            if not work or years > 30:
                continue
            explicit = bool(_MINIMUM.search(line[: match.start()])) or bool(
                re.search(r"\brequired\b", detail)
            )
            if section or explicit:
                mentioned.append(years)
            if (section == "required" or explicit) and not (
                section == "optional" or _OPTIONAL.search(line) or alternatives
            ):
                required.append(years)
    return required, mentioned


@lru_cache(maxsize=8192)
def infer_seniority(title: str, description: str) -> SeniorityGuess:
    t = title.lower()
    high_title: SeniorityGuess | None = None
    for pattern, level, confidence, why in _TITLE_RULES:
        m = pattern.search(t)
        if m and confidence == "high":
            high_title = SeniorityGuess(level, confidence, why.format(m=f"'{m.group(0)}'"))
            if level != "entry":
                return high_title
            break
    required, mentioned = _experience_requirements(description.lower())
    if required:
        years = max(required)
        level = _level_for_years(years)
        if high_title and level not in ("entry", "junior"):
            return SeniorityGuess(
                level,
                "medium",
                f"entry title conflicts with an explicit requirement "
                f"for {years}+ years of experience",
                years,
            )
        return SeniorityGuess(
            level, "high", f"description explicitly requires {years}+ years of experience", years
        )
    if high_title:
        return high_title
    mentioned_years = min(mentioned) if mentioned else None
    if mentioned_years is not None and mentioned_years <= 30:
        return SeniorityGuess(
            _level_for_years(mentioned_years),
            "medium",
            f"description mentions {mentioned_years}+ years of experience; "
            "requirement strength is unclear",
            mentioned_years,
        )
    for pattern, level, confidence, why in _TITLE_RULES:
        m = pattern.search(t)
        if m:
            return SeniorityGuess(level, confidence, why.format(m=f"'{m.group(0)}'"))
    return SeniorityGuess(None, None, "no seniority signal in title or description")
