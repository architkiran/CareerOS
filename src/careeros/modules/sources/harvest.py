"""Derive official ATS boards from real posting URLs.

Board tokens are never guessed: each one is read out of a live employer posting URL that a
listing feed (or the candidate's own saved jobs) already points at. The result is a watchlist
of employers that demonstrably post early-career roles on a public, permitted ATS endpoint.
"""

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "greenhouse",
        re.compile(r"https?://(?:job-boards|boards)\.greenhouse\.io/([A-Za-z0-9_-]+)/jobs/\d+"),
    ),
    ("lever", re.compile(r"https?://jobs\.lever\.co/([A-Za-z0-9_.-]+)/[0-9a-f-]{8,}")),
    ("ashby", re.compile(r"https?://jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)/[0-9a-f-]{8,}")),
    (
        "smartrecruiters",
        re.compile(r"https?://jobs\.smartrecruiters\.com/([A-Za-z0-9_-]+)/\d+"),
    ),
]
_WORKDAY = re.compile(
    r"https?://([a-z0-9-]+)\.(wd\d{1,3})\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?"
    r"([A-Za-z0-9_-]+)/job/"
)
_SKIP_TOKENS = {"embed", "jobs", "careers"}


@dataclass(frozen=True)
class Board:
    type: str
    token: str
    name: str
    listings: int


def board_from_url(url: str) -> tuple[str, str] | None:
    m = _WORKDAY.match(url)
    if m:
        return "workday", f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
    for kind, pattern in _PATTERNS:
        m = pattern.match(url)
        if m and m.group(1).lower() not in _SKIP_TOKENS and "%" not in m.group(1):
            return kind, m.group(1)
    return None


def harvest(listings: Iterable[tuple[str, str]], limit: int | None = None) -> list[Board]:
    """`listings` yields (posting_url, company_name). Most-referenced boards first."""
    counts: Counter[tuple[str, str]] = Counter()
    names: dict[tuple[str, str], Counter[str]] = {}
    for url, company in listings:
        key = board_from_url(url)
        if key is None:
            continue
        counts[key] += 1
        names.setdefault(key, Counter())[company.strip()] += 1
    boards = [
        Board(kind, token, names[(kind, token)].most_common(1)[0][0], n)
        for (kind, token), n in counts.most_common()
    ]
    return boards[:limit] if limit else boards


def to_toml(boards: Iterable[Board], header: str) -> str:
    lines = [f"# {line}" for line in header.splitlines()] + [""]
    for b in boards:
        name = b.name.replace("\\", " ").replace('"', "'")
        rate = {"workday": "1.5", "ashby": "3.0"}.get(b.type, "2.0")
        lines += [
            "[[source]]",
            f'type = "{b.type}"',
            f'token = "{b.token}"',
            f'name = "{name}"',
            f"rate_limit_seconds = {rate}",
            "",
        ]
    return "\n".join(lines)
