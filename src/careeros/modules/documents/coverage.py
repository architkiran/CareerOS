"""Content-loss checks supplement one-page PDF validation."""

from collections import Counter

from careeros.modules.documents.content import Candidate, DocumentContent, experience_paragraphs
from careeros.modules.documents.qa import Finding


def coverage_findings(content: DocumentContent, candidate: Candidate) -> list[Finding]:
    counts = Counter(
        ref
        for name, claims in content.sections
        if name == "Experience"
        for c in claims
        for ref in c.refs
    )
    findings = []
    for exp in candidate.experience:
        if counts[exp.ref] == 1 and experience_paragraphs(exp.text.split("|", 2)[-1]):
            findings.append(
                Finding(
                    "error",
                    "empty_experience",
                    "An included experience lost all its evidence bullets.",
                )
            )
        elif counts[exp.ref] == 0:
            findings.append(
                Finding(
                    "warning",
                    "experience_omitted",
                    f"Excluded experience: {exp.text.split('|', 1)[0]}. "
                    "Review this explicit omission.",
                )
            )
        elif 0 < counts[exp.ref] - 1 < len(experience_paragraphs(exp.text.split("|", 2)[-1])):
            findings.append(
                Finding(
                    "warning",
                    "experience_reduced",
                    f"Experience bullets were reduced for {exp.text.split('|', 1)[0]}. "
                    "Review these cuts.",
                )
            )
    included = {
        ref
        for name, claims in content.sections
        if name == "Leadership"
        for c in claims
        for ref in c.refs
    }
    for fact in candidate.other_facts:
        if fact.kind == "leadership" and fact.ref not in included:
            findings.append(
                Finding(
                    "error", "leadership_omitted", "A verified leadership activity was omitted."
                )
            )
    words = len(" ".join(c.text for c in content.claims()).split())
    available = sum(len(x.text.split()) for x in (*candidate.experience, *candidate.projects))
    if words < 280 and available > 350:
        findings.append(
            Finding(
                "warning",
                "low_content_coverage",
                "This version uses little of your evidence library. "
                "Review missing content before approval.",
            )
        )
    return findings
