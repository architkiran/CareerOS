"""Deterministic document content built only from verified profile items.

Every candidate-facing line is a Claim that lists the profile items supporting
it ("skill:<id>", "fact:<id>", "experience:<id>", "project:<id>", "profile:<id>").
Job details (title, company) are context, not claims about the candidate.
"""

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from careeros.modules.matching.text import contains_term


@dataclass(frozen=True)
class SourceItem:
    """A verified profile item usable as evidence, with the text it supports."""

    ref: str
    kind: str
    text: str
    skills: tuple[str, ...] = ()
    start: date | None = None
    end: date | None = None


@dataclass
class Claim:
    section: str
    text: str
    refs: list[str]


@dataclass
class DocumentContent:
    document_type: str
    template: str
    header: list[str]
    sections: list[tuple[str, list[Claim]]]
    context: dict[str, str] = field(default_factory=dict)
    excluded_unverified: int = 0

    def claims(self) -> list[Claim]:
        return [c for _, cs in self.sections for c in cs]

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_type": self.document_type,
            "template": self.template,
            "header": self.header,
            "context": self.context,
            "excluded_unverified": self.excluded_unverified,
            "sections": [[name, [asdict(c) for c in cs]] for name, cs in self.sections],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DocumentContent":
        return cls(
            d["document_type"],
            d["template"],
            list(d["header"]),
            [(name, [Claim(**c) for c in cs]) for name, cs in d["sections"]],
            dict(d.get("context", {})),
            int(d.get("excluded_unverified", 0)),
        )

    def as_text(self) -> str:
        lines = [*self.header, ""]
        for name, claims in self.sections:
            lines.append(name.upper())
            lines += [f"- {c.text}" if name not in ("Letter",) else c.text for c in claims]
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


@dataclass(frozen=True)
class Candidate:
    profile_ref: str
    name: str
    location: str | None
    email: str | None
    phone: str | None
    education: tuple[SourceItem, ...]
    other_facts: tuple[SourceItem, ...]
    skills: tuple[SourceItem, ...]
    experience: tuple[SourceItem, ...]  # text: "Title|Organization|description"
    projects: tuple[SourceItem, ...]  # text: "Name|description|outcome1\noutcome2"
    excluded_unverified: int


def _fmt_dates(item: SourceItem) -> str:
    def f(d: date | None) -> str:
        return d.strftime("%b %Y") if d else ""

    if not item.start and not item.end:
        return ""
    return f"{f(item.start) or '?'} to {f(item.end) or 'present'}"


def _relevance(item: SourceItem, job_text: str) -> int:
    return sum(1 for s in item.skills if contains_term(job_text, s))


def build_resume(
    c: Candidate, job_title: str, company: str, job_text: str, lane: str
) -> DocumentContent:
    job_low = job_text.lower() + " " + job_title.lower()
    header = [x for x in (c.name, " | ".join(v for v in (c.location, c.email, c.phone) if v)) if x]

    skills = sorted(c.skills, key=lambda s: (not contains_term(job_low, s.text), s.text.lower()))
    matched = [s for s in skills if contains_term(job_low, s.text)]
    sections: list[tuple[str, list[Claim]]] = []

    summary: list[Claim] = []
    if c.education:
        edu = c.education[0]
        focus = matched[:4] or skills[:4]
        text = edu.text
        refs = [edu.ref]
        if focus:
            text += f". Skills relevant to this role: {', '.join(s.text for s in focus)}"
            refs += [s.ref for s in focus]
        summary.append(Claim("Summary", text + ".", refs))
    if summary:
        sections.append(("Summary", summary))
    if c.education:
        sections.append(("Education", [Claim("Education", e.text, [e.ref]) for e in c.education]))
    if skills:
        sections.append(
            (
                "Skills",
                [Claim("Skills", ", ".join(s.text for s in skills), [s.ref for s in skills])],
            )
        )
    exp_claims: list[Claim] = []
    for e in sorted(c.experience, key=lambda x: x.start or date.min, reverse=True):
        title, org, desc = (e.text.split("|", 2) + ["", ""])[:3]
        dates = _fmt_dates(e)
        exp_claims.append(
            Claim("Experience", f"{title}, {org}" + (f" ({dates})" if dates else ""), [e.ref])
        )
        for line in (ln.strip(" -•\t") for ln in desc.splitlines()):
            if line:
                exp_claims.append(Claim("Experience", line, [e.ref]))
    if exp_claims:
        sections.append(("Experience", exp_claims))
    proj_claims: list[Claim] = []
    ranked = sorted(c.projects, key=lambda p: -_relevance(p, job_low))[:4]
    for p in ranked:
        name, desc, outcomes = (p.text.split("|", 2) + ["", ""])[:3]
        tech = f" ({', '.join(p.skills)})" if p.skills else ""
        proj_claims.append(
            Claim("Projects", f"{name}{tech}" + (f": {desc}" if desc else ""), [p.ref])
        )
        proj_claims += [
            Claim("Projects", o.strip(), [p.ref]) for o in outcomes.splitlines() if o.strip()
        ]
    if proj_claims:
        sections.append(("Projects", proj_claims))
    return DocumentContent(
        "resume",
        lane,
        header,
        sections,
        {"job_title": job_title, "company": company},
        c.excluded_unverified,
    )


def build_cover_letter(
    c: Candidate, job_title: str, company: str, job_text: str, lane: str
) -> DocumentContent:
    job_low = job_text.lower() + " " + job_title.lower()
    matched = [s for s in c.skills if contains_term(job_low, s.text)][:5]
    best = sorted(c.projects, key=lambda p: -_relevance(p, job_low))[:2]
    claims: list[Claim] = []
    if c.education:
        claims.append(
            Claim(
                "Letter",
                f"I am applying for the {job_title} role at {company}. "
                f"My background: {c.education[0].text}.",
                [c.education[0].ref],
            )
        )
    if matched:
        claims.append(
            Claim(
                "Letter",
                "The posting asks for skills I have used: "
                + ", ".join(s.text for s in matched)
                + ".",
                [s.ref for s in matched],
            )
        )
    for p in best:
        name, desc, _ = (p.text.split("|", 2) + ["", ""])[:3]
        claims.append(
            Claim(
                "Letter",
                f"In {name}, "
                + (
                    desc[0].lower() + desc[1:] if desc else f"I worked with {', '.join(p.skills)}"
                ).rstrip(".")
                + ".",
                [p.ref],
            )
        )
    header = [c.name] + [v for v in (c.email, c.phone) if v]
    return DocumentContent(
        "cover_letter",
        lane,
        header,
        [("Letter", claims)],
        {"job_title": job_title, "company": company},
        c.excluded_unverified,
    )
