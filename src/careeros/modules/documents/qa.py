"""Fact checks run on every generated version. Errors block; warnings need acknowledgment."""

import re
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from careeros.modules.documents.content import Candidate, DocumentContent, SourceItem, internal_note

Severity = Literal["error", "warning"]
_NUMBER = re.compile(
    r"(?P<number>\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(?P<scale>[kmb](?![a-z])|thousand\b|million\b|billion\b))?"
    r"(?:\s*(?P<percent>%))?",
    re.I,
)
_OWNERSHIP = re.compile(r"\b(led|headed|owned|managed a team|founded|spearheaded)\b", re.I)


@dataclass(frozen=True)
class Finding:
    severity: Severity
    check: str
    message: str
    claim: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def numeric_tokens(text: str) -> set[str]:
    """Compare values, including financial scale, without rejecting equivalent notation."""
    factors = {
        "k": 1000,
        "thousand": 1000,
        "m": 1000000,
        "million": 1000000,
        "b": 1000000000,
        "billion": 1000000000,
    }
    result = set()
    for match in _NUMBER.finditer(text):
        number = Decimal(match["number"].replace(",", ""))
        number *= factors.get((match["scale"] or "").lower(), 1)
        result.add(format(number.normalize(), "f") + ("%" if match["percent"] else ""))
    return result


def run_qa(content: DocumentContent, candidate: Candidate, today: date) -> list[Finding]:
    items: dict[str, SourceItem] = {
        i.ref: i
        for group in (
            candidate.education,
            candidate.other_facts,
            candidate.skills,
            candidate.experience,
            candidate.projects,
        )
        for i in group
    }
    items[candidate.profile_ref] = SourceItem(candidate.profile_ref, "profile", candidate.name)
    verified_skills = {s.text.lower() for s in candidate.skills}
    out: list[Finding] = []

    if any(internal_note(item.text) for item in items.values()):
        out.append(
            Finding(
                "warning",
                "internal_notes_excluded",
                "Internal profile notes were omitted. Review the underlying experience details.",
            )
        )
    for claim in content.claims():
        if internal_note(claim.text):
            out.append(
                Finding(
                    "error",
                    "internal_note",
                    "An internal editing instruction cannot appear in an application document.",
                    claim.text,
                )
            )
        sources = [items[r] for r in claim.refs if r in items]
        if not claim.refs or len(sources) != len(claim.refs):
            out.append(
                Finding(
                    "error",
                    "unsupported_claim",
                    "Not backed by a verified profile item.",
                    claim.text,
                )
            )
            continue
        source_text = " ".join(s.text + " " + " ".join(s.skills) for s in sources)
        allowed = numeric_tokens(source_text) | numeric_tokens(content.context.get("job_title", ""))
        extra = {
            n
            for n in numeric_tokens(claim.text)
            if n not in allowed and not _is_date_part(n, sources)
        }
        if extra:
            out.append(
                Finding(
                    "error",
                    "unsupported_number",
                    f"Number(s) {', '.join(sorted(extra))} don't appear in the supporting "
                    "profile item.",
                    claim.text,
                )
            )
        if _OWNERSHIP.search(claim.text) and not _OWNERSHIP.search(source_text):
            out.append(
                Finding(
                    "error",
                    "inflated_ownership",
                    "Claims leadership or ownership the profile doesn't state.",
                    claim.text,
                )
            )

    for name, claims in content.sections:
        if name == "Skills":
            for claim in claims:
                for skill in (s.strip() for s in claim.text.split(",")):
                    if skill and skill.lower() not in verified_skills:
                        out.append(
                            Finding(
                                "error",
                                "skill_not_in_profile",
                                f"'{skill}' isn't a verified skill.",
                                claim.text,
                            )
                        )
    for e in candidate.experience:
        title = e.text.split("|", 1)[0]
        if e.start is None:
            out.append(
                Finding(
                    "warning",
                    "missing_dates",
                    f"'{title}' has no start date; many applications require one.",
                )
            )
        elif e.start > today:
            out.append(Finding("warning", "future_date", f"'{title}' starts in the future."))
        if e.start and e.end and e.end < e.start:
            out.append(Finding("error", "contradictory_dates", f"'{title}' ends before it starts."))
    if content.excluded_unverified:
        out.append(
            Finding(
                "warning",
                "unverified_excluded",
                f"{content.excluded_unverified} unverified profile item(s) were left out. "
                "Verify them on your profile if they should be used.",
            )
        )
    if not content.claims():
        out.append(
            Finding(
                "error", "empty", "Nothing to put in this document: verify profile items first."
            )
        )
    return out


def _is_date_part(n: str, sources: list[SourceItem]) -> bool:
    years = {str(d.year) for s in sources for d in (s.start, s.end) if d}
    return n in years


def status_for(findings: list[Finding], acknowledged: bool) -> str:
    if any(f.severity == "error" for f in findings):
        return "blocked"
    if any(f.severity == "warning" for f in findings) and not acknowledged:
        return "needs_ack"
    return "ready"
