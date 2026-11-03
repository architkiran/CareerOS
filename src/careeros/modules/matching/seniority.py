"""Seniority is inferred, never treated as fact: always returned with confidence and rationale."""

import re
from dataclasses import dataclass
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
    r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?years?(?:\s+of)?[^.\n]{0,40}?experience"
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


def infer_seniority(title: str, description: str) -> SeniorityGuess:
    t = title.lower()
    for pattern, level, confidence, why in _TITLE_RULES:
        m = pattern.search(t)
        if m and confidence == "high":
            return SeniorityGuess(level, confidence, why.format(m=f"'{m.group(0)}'"))
    years_found = [int(m.group(1)) for m in _YEARS.finditer(description.lower())]
    years = min(years_found) if years_found else None
    if years is not None and years <= 30:
        return SeniorityGuess(
            _level_for_years(years),
            "medium",
            f"description asks for {years}+ years of experience",
            years,
        )
    for pattern, level, confidence, why in _TITLE_RULES:
        m = pattern.search(t)
        if m:
            return SeniorityGuess(level, confidence, why.format(m=f"'{m.group(0)}'"))
    return SeniorityGuess(None, None, "no seniority signal in title or description")
