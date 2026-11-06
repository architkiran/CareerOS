"""Read the user's own fixed LaTeX resume as data; never execute imported commands."""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from sqlalchemy.orm import Session

from careeros.db.models import CandidateSkill
from careeros.modules.events.service import record_event
from careeros.modules.profile import schemas
from careeros.modules.profile import service as profiles
from careeros.modules.sources.text import sha256
from careeros.modules.system.settings_store import get_setting, set_setting


@dataclass
class Entry:
    title: str
    extra: str
    dates: str
    bullets: list[str]


def group(text: str, offset: int) -> tuple[str, int]:
    while offset < len(text) and text[offset].isspace():
        offset += 1
    if offset >= len(text) or text[offset] != "{":
        raise ValueError("Master entry has an unsupported structure.")
    start = offset + 1
    depth = 1
    offset += 1
    while offset < len(text):
        if text[offset] in "{}" and (offset == 0 or text[offset - 1] != "\\"):
            depth += 1 if text[offset] == "{" else -1
            if depth == 0:
                return text[start:offset], offset + 1
        offset += 1
    raise ValueError("Unbalanced master content.")


def plain(text: str) -> str:
    text = re.sub(r"\\href\{[^{}]*\}\{([^{}]*)\}", r"\1", text)
    for _ in range(6):
        text = re.sub(r"\\(?:textbf|emph|textit)\{([^{}]*)\}", r"\1", text)
    text = text.replace(r"$\sim$", "~").replace(r"\&", "&").replace(r"\%", "%").replace(r"\_", "_")
    text = re.sub(r"\\(?:begin|end)\{[^{}]+\}", "", text)
    text = re.sub(r"\\[A-Za-z]+", "", text).replace("$", "").replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", text).strip()


class Master(TypedDict):
    summary: str
    experience: list[Entry]
    projects: list[Entry]
    education: list[str]
    skills: list[str]


def parse(source: str) -> Master:
    if len(source) > 200_000:
        raise ValueError("Master source exceeds the supported size.")
    # Comments, including optional achievements that are not yet built, are not facts.
    source = re.sub(r"(?m)(?<!\\)%.*$", "", source)
    sections = {}
    matches = list(re.finditer(r"\\section\{([^}]+)\}", source))
    for i, match in enumerate(matches):
        sections[match[1]] = source[
            match.end() : matches[i + 1].start() if i + 1 < len(matches) else len(source)
        ]
    parsed: Master = {
        "summary": plain(sections.get("Professional Summary", "")),
        "experience": [],
        "projects": [],
        "education": [],
        "skills": [],
    }
    for section, key in [("Work Experience", "experience"), ("Projects", "projects")]:
        body = sections.get(section, "")
        entries = []
        starts = list(re.finditer(r"\\entry", body))
        for i, start in enumerate(starts):
            left, pos = group(body, start.end())
            dates, pos = group(body, pos)
            chunk = body[pos : starts[i + 1].start() if i + 1 < len(starts) else len(body)]
            title, _, extra = plain(left).partition(" | ")
            bullets = [plain(x) for x in re.split(r"\\item\b", chunk)[1:]]
            entries.append(Entry(title, extra, plain(dates), [x for x in bullets if x]))
        if key == "experience":
            parsed["experience"] = entries
        else:
            parsed["projects"] = entries
    parsed["education"] = []
    body = sections.get("Education", "")
    for match in re.finditer(r"\\entry", body):
        left, pos = group(body, match.end())
        right, _ = group(body, pos)
        parsed["education"].append(plain(left) + " (" + plain(right) + ")")
    skills: list[str] = []
    for part in re.split(r"\\item\b", sections.get("Skills", ""))[1:]:
        _, _, value = plain(part).partition(":")
        skills.extend(x.strip() for x in re.split(r"[,()]", value) if x.strip())
    parsed["skills"] = list(dict.fromkeys(skills))
    return parsed


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


ALIASES = {
    "awsfinancialtransactiondatapipeline": "awsfinancialdatapipeline",
    "mbtarapidtransitperformanceanalytics": "mbtatransitperformanceanalysis",
}


def import_user_master(
    session: Session, path: Path, *, confirm_user_authored: bool = False
) -> dict[str, object]:
    if not confirm_user_authored:
        raise ValueError(
            "Only explicitly user-authored master content can be imported as verified evidence."
        )
    raw = path.read_text()
    digest = sha256(raw)
    previous = get_setting(session, "resume.master", {})
    if isinstance(previous, dict) and previous.get("hash") == digest:
        return previous
    data = parse(raw)
    profile = profiles.get_or_create_profile(session)
    exps = profiles.list_experience(session, profile.id)
    projects = profiles.list_projects(session, profile.id)
    exp_refs = []
    for e in data["experience"]:
        org = e.extra.split(",")[0]
        exp = next((x for x in exps if _key(x.organization) == _key(org)), None)
        dates = re.findall(r"[A-Z][a-z]{2} \d{4}", e.dates)
        starts = datetime.strptime(dates[0], "%b %Y").date() if dates else None
        ends = datetime.strptime(dates[1], "%b %Y").date() if len(dates) > 1 else None
        payload = schemas.ExperienceIn(
            organization=org,
            title=e.title,
            start_date=starts,
            end_date=ends,
            description="\n".join(e.bullets),
            verified_status="verified",
        )
        if exp is None:
            exp = profiles.add_experience(session, payload)
        else:
            for field, value in payload.model_dump().items():
                setattr(exp, field, value)
        exp_refs.append("experience:" + exp.id)
    project_refs = []
    for p in data["projects"]:
        key = ALIASES.get(_key(p.title), _key(p.title))
        project = next((x for x in projects if _key(x.name) == key), None)
        project_payload = schemas.ProjectIn(
            name=p.title,
            technologies=[v.strip() for v in re.split(r"[,()]", p.extra) if v.strip()],
            description="",
            outcomes=p.bullets,
            evidence_notes=f"User-authored master sha256:{digest}",
            verified_status="verified",
        )
        if project is None:
            project = profiles.add_project(session, project_payload)
        else:
            project.name, project.description = project_payload.name, project_payload.description
            project.technologies_json, project.outcomes_json = (
                project_payload.technologies,
                project_payload.outcomes,
            )
            project.evidence_notes, project.verified_status = (
                project_payload.evidence_notes,
                "verified",
            )
        project_refs.append("project:" + project.id)
    facts = profiles.list_facts(session, profile.id)
    imports: list[tuple[str, str, schemas.FactCategory]] = [
        ("Master professional summary", str(data["summary"]), "employment"),
        *[
            (f"Master education {i + 1}", str(v), "education")
            for i, v in enumerate(data["education"])
        ],
    ]
    for label, value, category in imports:
        existing = next(
            (
                f
                for f in facts
                if f.fact_key == label
                or (
                    category == "education"
                    and f.category == "education"
                    and ("Boston University" if "Boston University" in value else "Ramaiah")
                    in f.fact_value
                )
            ),
            None,
        )
        if existing:
            existing.fact_value, existing.source_note, existing.verified_status = (
                value,
                f"User master sha256:{digest}",
                "verified",
            )
        else:
            profiles.add_fact(
                session,
                schemas.FactIn(
                    category=category,
                    fact_key=label,
                    fact_value=value,
                    source_note=f"User master sha256:{digest}",
                    verified_status="verified",
                ),
            )
    for skill in data["skills"]:
        known = profiles.find_skill(session, skill)
        cs = session.get(CandidateSkill, (profile.id, known.id)) if known else None
        if cs:
            cs.verified_status = "verified"
        else:
            profiles.add_skill(session, schemas.SkillIn(name=skill, verified_status="verified"))
    for i, url in enumerate(re.findall(r"\\href\{(https://[^{}]+)\}", raw)):
        key = f"Master public link {i + 1}"
        if not any(f.fact_key == key for f in facts):
            profiles.add_fact(
                session,
                schemas.FactIn(
                    category="contact",
                    fact_key=key,
                    fact_value=url,
                    source_note=f"User master sha256:{digest}",
                    verified_status="verified",
                ),
            )
    report = {
        "hash": digest,
        "experience_refs": exp_refs,
        "project_refs": project_refs,
        "experience_count": len(exp_refs),
        "project_count": len(project_refs),
        "skills_count": len(data["skills"]),
    }
    set_setting(session, "resume.master", report)
    record_event(
        session,
        "resume.master_imported",
        "Imported user-authored master evidence with source hash.",
        metadata={"hash": digest, "experiences": len(exp_refs), "projects": len(project_refs)},
    )
    session.flush()
    return report
