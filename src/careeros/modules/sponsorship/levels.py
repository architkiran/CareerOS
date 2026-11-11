"""Sponsorship evidence levels A / B / C / D / U. Pure functions; no I/O.

    A  explicit role-level support, quoted from the posting itself
    B  employer-level public LCA history; this role is NOT confirmed
    C  indirect or third-party signal, or an unconfirmed employer-name match
    D  the posting itself rules sponsorship out (or requires citizenship / clearance)
    U  no credible evidence either way

A level is a category of evidence, never a probability and never legal advice.
"""

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from careeros.modules.matching.filters import authorization_claims
from careeros.modules.matching.text import excerpt

Level = Literal["A", "B", "C", "D", "U"]

LEVEL_LABEL = {
    "A": "Role-level sponsorship support stated",
    "B": "Employer history found; role sponsorship unconfirmed",
    "C": "Indirect or third-party signal only",
    "D": "Posting rules out sponsorship",
    "U": "Unknown: no credible evidence",
}

# Wording the original filters miss. Each must be unambiguous about the *employer's* position.
_NEGATIVE = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"(?:u\.?s\.?|united states)\s+citizens?\s+(?:or|and|/)\s+(?:lawful\s+)?"
        r"(?:permanent\s+residents?|green\s+card)",
        r"must\s+be\s+(?:a\s+)?u\.?s\.?\s+person",
        r"(?:permanent|unrestricted|indefinite)\s+(?:u\.?s\.?\s+)?work\s+authorization",
        r"authorized\s+to\s+work\s+(?:in\s+the\s+(?:u\.?s\.?|united states)\s+)?"
        r"(?:on\s+a\s+)?(?:permanent|unrestricted|indefinite)\s+basis",
        r"(?:not|cannot|unable\s+to|won't|will\s+not|does\s+not|do\s+not)\s+[^.\n]{0,60}"
        r"\b(?:opt|cpt|stem\s+opt|f-?1|h-?1b)\b",
        r"(?:without|not\s+require|no\s+need\s+for)\s+[^.\n]{0,40}sponsorship\s+"
        r"(?:now\s+or\s+in\s+the\s+future|in\s+the\s+future)",
        r"(?:now\s+or\s+in\s+the\s+future|future)\s+[^.\n]{0,30}sponsorship[^.\n]{0,40}"
        r"(?:not\s+(?:be\s+)?(?:eligible|considered)|will\s+not)",
        r"sponsorship\s+(?:is\s+|will\s+)?not\s+(?:be\s+)?(?:available|provided|offered|"
        r"supported|considered)",
        r"(?:does|do|will|can)\s*(?:not|n't)\s+(?:offer|provide|support)\s+[^.\n]{0,30}"
        r"(?:sponsorship|work\s+visas?)",
        r"not\s+(?:able|in\s+a\s+position)\s+to\s+(?:offer|provide)\s+[^.\n]{0,30}sponsorship",
        r"\bitar\b|export\s+control[^.\n]{0,60}(?:u\.?s\.?\s+person|citizen)",
    )
]
_POSITIVE = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"(?:visa|immigration|h-?1b|work\s+authorization)\s+sponsorship\s+(?:is\s+)?"
        r"(?:available|offered|provided|supported|possible)",
        r"(?:we|company|employer)\s+(?:will|can|do|does|are\s+able\s+to)\s+sponsor\b",
        r"(?:open|willing|happy|able)\s+to\s+sponsor(?:ing)?\b",
        r"eligible\s+for\s+(?:visa\s+|immigration\s+|employment\s+)?sponsorship",
        r"sponsorship\s+(?:will\s+be|is)\s+considered",
        r"(?:welcome|accept|consider)s?\s+[^.\n]{0,30}\b(?:opt|stem\s+opt|f-?1)\b",
    )
]
_MENTION = re.compile(
    r"sponsor|work\s+authori[sz]ation|authori[sz]ed\s+to\s+work|e-?verify|\bvisa\b",
    re.IGNORECASE,
)

RECRUITER_QUESTIONS = {
    "B": "Does this specific role and team support H-1B sponsorship for a new graduate "
    "starting on F-1 OPT?",
    "C": "Can you confirm whether this role is open to candidates on F-1 OPT who will later "
    "need H-1B sponsorship?",
    "U": "Is this role open to candidates who will need employer sponsorship in the future?",
    "A": "The posting mentions sponsorship. Does that apply to this role, location and "
    "hiring cycle?",
}


@dataclass(frozen=True)
class EvidenceItem:
    scope: str  # role | employer | third_party
    polarity: str  # supports | rules_out | neutral
    claim: str
    source_name: str
    source_url: str | None = None
    quote: str | None = None
    observed_at: str | None = None


@dataclass(frozen=True)
class LcaSummary:
    """What the imported DOL disclosure data says about a legal employer name."""

    match: Literal["exact", "possible"]
    employer_names: tuple[str, ...]
    fiscal_years: tuple[int, ...]
    certified_total: int
    analyst_like: int
    top_titles: tuple[str, ...] = ()
    source_file: str = ""


@dataclass(frozen=True)
class Assessment:
    level: Level
    label: str
    summary: str
    items: tuple[EvidenceItem, ...] = ()
    unknowns: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    recruiter_question: str | None = None
    ambiguous_wording: bool = False
    disclaimer: str = field(
        default="Evidence category, not a probability or a legal determination."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def posting_claims(text: str) -> list[tuple[str, str]]:
    """(claim, quote) pairs: no_sponsorship | citizenship_required | sponsorship_offered."""
    claims = list(authorization_claims(text))
    kinds = {c for c, _ in claims}
    if "no_sponsorship" not in kinds and "citizenship_required" not in kinds:
        for pattern in _NEGATIVE:
            m = pattern.search(text)
            if m:
                claims.append(("no_sponsorship", excerpt(text, m)))
                kinds.add("no_sponsorship")
                break
    if "sponsorship_offered" not in kinds and not kinds & {
        "no_sponsorship",
        "citizenship_required",
    }:
        for pattern in _POSITIVE:
            m = pattern.search(text)
            if m:
                claims.append(("sponsorship_offered", excerpt(text, m)))
                break
    if any(c in ("no_sponsorship", "citizenship_required") for c, _ in claims):
        claims = [c for c in claims if c[0] != "sponsorship_offered"]  # a refusal wins
    return claims


def assess(
    *,
    description: str,
    posting_url: str | None,
    posting_is_official: bool,
    observed_at: str | None,
    feed_flag: str | None = None,
    feed_name: str | None = None,
    lca: LcaSummary | None = None,
) -> Assessment:
    items: list[EvidenceItem] = []
    contradictions: list[str] = []
    claims = posting_claims(description) if description else []
    source_name = "Employer posting" if posting_is_official else "Posting text via third party"
    negative = [c for c in claims if c[0] in ("no_sponsorship", "citizenship_required")]
    positive = [c for c in claims if c[0] == "sponsorship_offered"]
    for claim, quote in negative:
        items.append(
            EvidenceItem(
                "role",
                "rules_out",
                "Requires US citizenship, permanent residency or clearance"
                if claim == "citizenship_required"
                else "States it will not sponsor",
                source_name,
                posting_url,
                quote,
                observed_at,
            )
        )
    for _, quote in positive:
        items.append(
            EvidenceItem(
                "role",
                "supports",
                "States sponsorship is available or considered",
                source_name,
                posting_url,
                quote,
                observed_at,
            )
        )
    flag = (feed_flag or "").strip().lower()
    feed_polarity = None
    if flag == "offers sponsorship":
        feed_polarity = "supports"
    elif flag in ("does not offer sponsorship", "u.s. citizenship is required"):
        feed_polarity = "rules_out"
    if feed_polarity:
        items.append(
            EvidenceItem(
                "third_party",
                feed_polarity,
                f"Community list tags this role: {feed_flag}",
                feed_name or "Community listing feed",
                posting_url,
                None,
                observed_at,
            )
        )
    if lca is not None:
        years = ", ".join(f"FY{y}" for y in lca.fiscal_years)
        names = "; ".join(lca.employer_names[:3])
        claim = (
            f"{lca.certified_total} certified LCA filings ({years}) under: {names}. "
            f"{lca.analyst_like} for analyst, data or business occupations."
        )
        if lca.match == "possible":
            claim = "Name is similar, legal entity not confirmed. " + claim
        items.append(
            EvidenceItem(
                "employer",
                "supports",
                claim,
                "US DOL OFLC LCA disclosure data",
                "https://www.dol.gov/agencies/eta/foreign-labor/performance",
                ("Common titles: " + "; ".join(lca.top_titles[:4])) if lca.top_titles else None,
                lca.source_file or None,
            )
        )

    ambiguous = bool(description) and not claims and bool(_MENTION.search(description))
    unknowns: list[str] = []
    if negative:
        level: Level = "D"
        summary = "The posting itself rules this out for a candidate who needs sponsorship."
        if lca is not None:
            contradictions.append(
                "The employer has filed LCAs before, but this posting excludes sponsorship. "
                "The posting governs this role."
            )
    elif positive:
        level = "A"
        summary = "The posting states sponsorship is available or considered for this role."
        if feed_polarity == "rules_out":
            contradictions.append("A community list tags this role as not sponsoring.")
        if not posting_is_official:
            unknowns.append("Quote came through a third party; confirm on the employer page.")
    elif lca is not None and lca.match == "exact":
        level = "B"
        summary = (
            "The employer has certified LCA filings on record. That is history for the "
            "employer, not confirmation for this role."
        )
        unknowns += [
            "Whether this team, role and location sponsor in this hiring cycle.",
            "Whether new graduates on F-1 OPT are considered.",
        ]
        if feed_polarity == "rules_out":
            contradictions.append("A community list tags this role as not sponsoring.")
    elif feed_polarity or lca is not None:
        level = "C"
        summary = "Only indirect evidence. Not verified eligibility."
        if lca is not None:
            unknowns.append("Whether the LCA filer is the same legal entity as this employer.")
        if feed_polarity:
            unknowns.append("The community tag is unverified; the employer has not stated it.")
    else:
        level = "U"
        summary = "Neither the posting nor public records settle it."
        unknowns.append(
            "Posting text does not address sponsorship."
            if description
            else "No posting text was available to read."
        )
        if lca is None:
            unknowns.append("No employer LCA history matched (or LCA data not imported yet).")
    if ambiguous:
        unknowns.append(
            "The posting mentions work authorization without a clear position. Read it yourself."
        )
    if contradictions and level in ("A", "B"):
        summary += " Conflicting evidence exists; review before relying on it."
    return Assessment(
        level=level,
        label=LEVEL_LABEL[level],
        summary=summary,
        items=tuple(items),
        unknowns=tuple(unknowns),
        contradictions=tuple(contradictions),
        recruiter_question=RECRUITER_QUESTIONS.get(level),
        ambiguous_wording=ambiguous,
    )
