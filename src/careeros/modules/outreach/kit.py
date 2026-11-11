"""Outreach kit for one role: who to look for and what to say. Drafts only, never sent.

Applications alone rarely reach a recruiter. For every role worth pursuing the candidate gets
people-search links (opened by them, in their own signed-in browser; nothing is scraped) and
short editable drafts. Text is deterministic and built only from facts already on the card.
"""

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import quote

NOTE_LIMIT = 300  # LinkedIn connection-note limit
DEFAULT_INTRO = "I'm finishing my master's degree and looking for my first full-time role"


@dataclass(frozen=True)
class Draft:
    key: str
    label: str
    text: str
    limit: int | None = None


def _search(keywords: str) -> str:
    return "https://www.linkedin.com/search/results/people/?keywords=" + quote(keywords)


def _short(title: str) -> str:
    return title.split(" - ")[0].split(",")[0].split("(")[0].strip()[:60]


def build_kit(
    *,
    company: str,
    title: str,
    family_label: str | None,
    recruiter_question: str | None,
    candidate_name: str,
    school: str | None = None,
    intro: str = DEFAULT_INTRO,
) -> dict[str, Any]:
    role = _short(title)
    area = (family_label or "analytics").lower()
    first = candidate_name.split()[0] if candidate_name.strip() else ""
    sign = f" Thanks, {first}" if first else " Thank you."
    searches = [
        ("Recruiters at " + company, _search(f'"{company}" recruiter OR "talent acquisition"')),
        ("People in this kind of role", _search(f'"{company}" {role}')),
    ]
    if school:
        searches.insert(0, (f"{school} alumni at {company}", _search(f'"{company}" "{school}"')))
    note = (
        f"Hi [name], {intro}. I saw the {role} opening at {company} and would value "
        f"10 minutes on how you got started there.{sign}"
    )
    if len(note) > NOTE_LIMIT:
        note = (
            f"Hi [name], I saw the {role} opening at {company} and would value 10 minutes "
            f"on how you got started there.{sign}"
        )
    question = recruiter_question or (
        "is this role open to candidates who will need employer sponsorship in the future?"
    )
    drafts = [
        Draft("connect", "Connection note to someone on the team", note[:NOTE_LIMIT], NOTE_LIMIT),
        Draft(
            "recruiter",
            "Message to a recruiter",
            f"Hi [name], I'm interested in the {role} role at {company}. {intro}, with a "
            f"background in {area}. Before I apply I want to respect your time with one "
            f"question: {question} "
            f"Happy to share my resume.{sign}",
        ),
        Draft(
            "follow_up",
            "Follow-up a week after applying",
            f"Hi [name], I applied for the {role} role at {company} last week and remain very "
            f"interested. Is there anything else I can share that would help with the "
            f"review?{sign}",
        ),
    ]
    return {"searches": searches, "drafts": [asdict(d) for d in drafts]}
