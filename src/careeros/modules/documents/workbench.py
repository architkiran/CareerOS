"""A revision is explicit user choices and edits, never a change to master facts."""

import re
from dataclasses import replace
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from careeros.common.clock import utcnow
from careeros.modules.documents.content import (
    Candidate,
    Claim,
    DocumentContent,
    experience_paragraphs,
    internal_note,
)
from careeros.modules.documents.tailoring import relevance, terms


class Choices(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_refs: list[str] = Field(default_factory=list, max_length=20)
    experience_refs: list[str] = Field(default_factory=list, max_length=20)
    skills: list[str] = Field(default_factory=list, max_length=100)
    summary: str = Field(default="", max_length=2000)
    experience_edits: dict[str, str] = Field(default_factory=dict, max_length=20)
    feedback: str = Field(default="", max_length=3000)


def selected_candidate(candidate: Candidate, choices: Choices) -> Candidate:
    projects = {p.ref for p in candidate.projects}
    experiences = {e.ref for e in candidate.experience}
    skills = {s.text for s in candidate.skills}
    if (
        not set(choices.project_refs) <= projects
        or not set(choices.experience_refs) <= experiences
        or not set(choices.skills) <= skills
    ):
        raise ValueError("Selections must refer to verified profile evidence.")
    if not choices.experience_refs and experiences:
        raise ValueError(
            "Keep at least one experience. Excluding every role would lose your work history."
        )
    if not choices.project_refs and projects:
        raise ValueError("Choose at least one project from your verified library.")
    return replace(
        candidate,
        projects=tuple(p for p in candidate.projects if p.ref in choices.project_refs),
        experience=tuple(e for e in candidate.experience if e.ref in choices.experience_refs),
        skills=tuple(s for s in candidate.skills if s.text in choices.skills),
    )


_CONNECTORS = set(
    [
        "a",
        "an",
        "to",
        "in",
        "on",
        "at",
        "of",
        "by",
        "as",
        "for",
        "and",
        "or",
        "with",
        "the",
        "is",
        "are",
        "was",
        "were",
        "i",
        "my",
        "me",
        "using",
        "use",
        "used",
        "building",
        "built",
        "develop",
        "developed",
        "creating",
        "created",
        "experienced",
        "experience",
        "background",
        "work",
        "working",
        "focused",
        "focus",
        "includes",
        "include",
        "professional",
        "analyst",
        "engineer",
        "data",
        "engineering",
        "analysis",
        "analytics",
        "specialist",
    ]
)


def validate_edit(text: str, evidence: str) -> None:
    if internal_note(text):
        raise ValueError("Editing instructions belong in feedback, not in the resume.")
    # Reject factual additions rather than trusting a fluent paraphrase. Existing
    # numeric and ownership QA independently checks the saved claims as well.
    from careeros.modules.agents.support import TERMS
    from careeros.modules.matching.text import contains_term

    numbers = set(re.findall(r"\d[\d,.]*%?", text)) - set(re.findall(r"\d[\d,.]*%?", evidence))
    tools = (
        *TERMS,
        "Rust",
        "C++",
        "JavaScript",
        "TypeScript",
        "Azure",
        "Flink",
        "TensorFlow",
        "PyTorch",
        "Vertex AI",
        "Vertex Vector Search",
        "FastAPI",
        "Flask",
        "DuckDB",
        "DAX",
        "Power Query",
        "GitHub Actions",
        "Prometheus",
    )
    new_tools = [
        tool for tool in tools if contains_term(text, tool) and not contains_term(evidence, tool)
    ]
    ownership = re.findall(r"\b(led|headed|founded|spearheaded|managed a team|owned)\b", text, re.I)
    unsupported_ownership = any(
        not re.search(r"\b" + re.escape(claim) + r"\b", evidence, re.I) for claim in ownership
    )
    tenure = re.findall(r"\b\d+(?:\.\d+)?\+?\s+(?:years?|yrs?)(?: of experience)?\b", text, re.I)
    unsupported_tenure = any(claim.lower() not in evidence.lower() for claim in tenure)
    protected = (
        "US citizen",
        "U.S. citizen",
        "permanent resident",
        "green card",
        "unrestricted work authorization",
        "no sponsorship",
        "authorized to work",
        "security clearance",
        "PhD",
        "Ph.D",
        "certified",
    )
    unsupported_identity = any(
        contains_term(text, claim) and not contains_term(evidence, claim) for claim in protected
    )
    domain_terms = {
        "financial",
        "finance",
        "transaction",
        "transactions",
        "fraud",
        "payments",
        "revenue",
        "sales",
        "healthcare",
        "clinical",
        "banking",
        "investment",
        "trading",
        "compliance",
        "regulatory",
        "customers",
        "clients",
    }
    new_domain = (terms(text) & domain_terms) - terms(evidence)
    # Legitimate rephrasing can introduce ordinary words; facts, tools, metrics and
    # ownership cannot be introduced by either a person editing here or a model.
    content_words = terms(text) - _CONNECTORS
    overlap = len(content_words & terms(evidence)) / max(1, len(content_words))
    if (
        numbers
        or new_tools
        or new_domain
        or unsupported_ownership
        or unsupported_tenure
        or unsupported_identity
        or (len(content_words) > 4 and overlap < 0.35)
    ):
        raise ValueError(
            "This edit adds unverified detail. Verify new facts in your profile first. "
            + ", ".join(sorted(numbers | set(new_tools) | new_domain)[:8])
        )


def apply_edits(content: DocumentContent, candidate: Candidate, choices: Choices) -> None:
    all_evidence = "\n".join(
        x.text + " " + " ".join(x.skills)
        for group in (
            candidate.education,
            candidate.other_facts,
            candidate.experience,
            candidate.projects,
            candidate.skills,
        )
        for x in group
    )
    refs = [
        x.ref
        for group in (
            candidate.education,
            candidate.other_facts,
            candidate.experience,
            candidate.projects,
            candidate.skills,
        )
        for x in group
    ]
    if choices.summary.strip():
        validate_summary(choices.summary, all_evidence, candidate)
        content.sections = [
            (
                name,
                [Claim("Summary", choices.summary.strip(), refs)] if name == "Summary" else claims,
            )
            for name, claims in content.sections
        ]
        if not any(name == "Summary" for name, _ in content.sections):
            content.sections.insert(
                0, ("Summary", [Claim("Summary", choices.summary.strip(), refs)])
            )
    for ref, text in choices.experience_edits.items():
        exp = next((e for e in candidate.experience if e.ref == ref), None)
        if exp is None:
            raise ValueError("An experience edit must refer to a selected verified role.")
        paragraphs = experience_paragraphs(text)
        if not paragraphs:
            raise ValueError("An included experience cannot have an empty description.")
        validate_edit(text, exp.text)
        for name, claims in content.sections:
            if name == "Experience":
                positions = [i for i, c in enumerate(claims) if c.refs == [ref]]
                if positions:
                    head = claims[positions[0]]
                    claims[:] = [c for c in claims if c.refs != [ref]]
                    claims[positions[0] : positions[0]] = [
                        head,
                        *[Claim("Experience", p, [ref]) for p in paragraphs],
                    ]
    content.context["feedback"] = choices.feedback
    content.context["editor"] = "evidence-workbench-v1"
    content.context["choices"] = choices.model_dump_json()


def inventory(candidate: Candidate, job_text: str) -> list[dict[str, object]]:
    return [
        {
            "ref": p.ref,
            "name": p.text.split("|")[0],
            "score": relevance(p, job_text),
            "text": p.text.replace("|", "\n"),
            "technologies": p.skills,
        }
        for p in sorted(candidate.projects, key=lambda p: (-relevance(p, job_text), p.ref))
    ]


def recommended_skills(candidate: Candidate, project_refs: list[str], job_text: str) -> list[str]:
    """Known JD skills plus skills actually stated in the selected project evidence."""
    from careeros.modules.matching.text import contains_term

    project_tools = " ".join(
        " ".join(p.skills) for p in candidate.projects if p.ref in project_refs
    )
    core = {"python", "sql", "excel", "tableau", "power bi", "pandas", "duckdb"}
    return [
        s.text
        for s in candidate.skills
        if contains_term(job_text, s.text)
        or contains_term(project_tools, s.text)
        or (contains_term(job_text, "analyst") and s.text.lower() in core)
    ]


def validate_summary(text: str, evidence: str, candidate: Candidate) -> None:
    validate_edit(text, evidence)
    current_month = utcnow().date().replace(day=1)
    for education in candidate.education:
        month_names = (
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        )
        dates = [
            date(int(year), month_names.index(month.lower()[:3]) + 1, 1)
            for month, year in re.findall(
                r"\b(Jan[a-z]*|Feb[a-z]*|Mar[a-z]*|Apr[a-z]*|May|Jun[a-z]*|Jul[a-z]*|Aug[a-z]*|Sep[a-z]*|Oct[a-z]*|Nov[a-z]*|Dec[a-z]*)\s+(20\d{2})\b",
                education.text,
                re.I,
            )
        ]
        education_end = education.end or (max(dates) if dates else None)
        in_progress = (education_end is not None and education_end >= current_month) or bool(
            re.search(r"candidate|expected|pursuing|in.progress|graduating", education.text, re.I)
        )
        if not in_progress:
            continue
        source = education.text.lower()
        degree = (
            r"(?:m\.?s\.?c?\b|master(?:'?s)?(?: of science)?)"
            if re.search(r"\bmaster|\bm\.?s\.?\b", source)
            else r"(?:ph\.?d\.?|doctorate|doctoral degree)"
            if re.search(r"ph\.?d|doctorate|doctoral", source)
            else r"(?:bachelor(?:'?s)?|b\.?s\.?|b\.?e\.?)"
        )
        completed = (
            r"\b(?:holds?|earned|completed|received|obtained|graduated with)\b"
            r"[^.!?\n]{0,60}\b" + degree
        )
        has_degree = r"\bhas\s+(?:an?|the)\s+" + degree
        degree_holder = degree + r"\s+(?:degree\s+)?(?:holder|graduate(?!\s+student\b))\b"
        if any(
            re.search(pattern, text, re.I) for pattern in (completed, has_degree, degree_holder)
        ):
            raise ValueError(
                "A degree still in progress cannot be described as earned or completed."
            )
