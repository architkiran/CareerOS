import re
from functools import lru_cache

from careeros.modules.sources.text import normalize_key

SENIORITY_ORDER = ("entry", "junior", "mid", "senior", "lead")


@lru_cache(maxsize=4096)
def term_pattern(term: str) -> re.Pattern[str]:
    """Whole-term, case-insensitive match that works for 'C++', 'Power BI', 'A/B testing'."""
    return re.compile(rf"(?<![\w]){re.escape(term.strip().lower())}(?![\w])")


def contains_term(text: str, term: str) -> bool:
    return bool(term.strip()) and term_pattern(term).search(text.lower()) is not None


def excerpt(text: str, match: re.Match[str], width: int = 90) -> str:
    start = max(match.start() - width, 0)
    end = min(match.end() + width, len(text))
    snippet = " ".join(text[start:end].split())
    return ("…" if start else "") + snippet + ("…" if end < len(text) else "")


def title_key(title: str) -> str:
    return normalize_key(title)
