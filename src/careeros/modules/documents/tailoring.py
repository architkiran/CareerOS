"""Explainable evidence selection. Job text ranks verified facts; it cannot create facts."""

import re
from dataclasses import asdict, dataclass

from careeros.modules.documents.content import Candidate, SourceItem, experience_paragraphs
from careeros.modules.matching.text import contains_term

_STOP = frozenset(
    [
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "will",
        "your",
        "our",
        "have",
        "experience",
        "role",
        "work",
        "team",
        "years",
        "ability",
        "including",
        "preferred",
        "required",
        "company",
        "skills",
        "responsibilities",
        "must",
    ]  # noqa: SIM905
)


def terms(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z][a-z0-9+#.-]{1,}", text.lower()) if t not in _STOP}


def relevance(item: SourceItem, description: str) -> int:
    advertised = terms(description)
    # Explicit skills receive more weight than general words, and title/business context counts.
    score = 5 * sum(contains_term(description, skill) for skill in item.skills) + len(
        terms(item.text) & advertised
    )
    # A completed project is stronger application evidence than a proposed or
    # unfinished one with the same technologies. Its stated status is preserved.
    if re.search(r"\b(?:in progress|planned|not yet completed)\b", item.text, re.I):
        score -= 15
    return score


@dataclass(frozen=True)
class TailoringReport:
    algorithm: str
    target_role: str
    matched_verified_skills: list[str]
    selected_projects: list[str]
    project_reasons: list[str]
    selected_experiences: list[str]
    source_refs: list[str]
    note: str = (
        "Only verified evidence is selected. Missing requirements are not added as qualifications."
    )


def plan(
    candidate: Candidate,
    title: str,
    description: str,
    project_limit: int = 3,
    experience_limit: int = 2,
) -> TailoringReport:
    target = title + "\n" + description
    projects = sorted(candidate.projects, key=lambda p: (-relevance(p, target), p.ref))[
        :project_limit
    ]
    experiences = sorted(
        candidate.experience,
        key=lambda p: (
            not bool(experience_paragraphs(p.text.split("|", 2)[-1])),
            -(p.start.toordinal() if p.start else 0),
            p.ref,
        ),
    )[:experience_limit]
    return TailoringReport(
        "verified-selection-v3",
        title,
        [
            s.text
            for s in sorted(candidate.skills, key=lambda s: s.text.lower())
            if contains_term(target, s.text)
        ],
        [p.text.split("|", 1)[0] for p in projects],
        [
            ", ".join(sorted(terms(p.text + " " + " ".join(p.skills)) & terms(target))[:8])
            or "Additional verified project evidence"
            for p in projects
        ],
        [p.text.split("|", 2)[0] for p in experiences],
        [p.ref for p in projects] + [p.ref for p in experiences],
    )


def report_dict(report: TailoringReport) -> dict[str, object]:
    return asdict(report)
