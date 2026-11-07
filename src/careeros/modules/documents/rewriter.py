"""Model-generated proposals are private, source-bound, and reviewed before PDF generation."""

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.common.fs import private_dir
from careeros.config import Settings
from careeros.db.models import Application, Job
from careeros.modules.documents.content import Candidate, experience_paragraphs
from careeros.modules.documents.service import load_candidate
from careeros.modules.documents.workbench import Choices, validate_edit, validate_summary
from careeros.modules.models.gateway import (
    GatewayResult,
    ModelGateway,
    ModelOutputError,
    ModelUnavailable,
)
from careeros.modules.sources.text import sha256


class RoleRewrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str
    bullets: list[str] = Field(min_length=1, max_length=10)


class SummaryRewrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=30, max_length=1000)


class Rewrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=30, max_length=1000)
    experience: list[RoleRewrite] = Field(min_length=1, max_length=20)
    project_refs: list[str] = Field(min_length=1, max_length=4)
    skills: list[str] = Field(min_length=1, max_length=18)
    rationale: str = Field(max_length=1000)


def fingerprint(session: Session, app_id: str) -> str:
    app = session.get(Application, app_id)
    if not app:
        raise LookupError("Application not found")
    job = session.get(Job, app.job_id)
    assert job
    return sha256(
        json.dumps(
            [asdict(load_candidate(session)), job.description_hash, job.title],
            sort_keys=True,
            default=str,
        )
    )


def propose(
    session: Session, app_id: str, root: Path, settings: Settings, feedback: str = ""
) -> dict[str, Any]:
    app = session.get(Application, app_id)
    if not app:
        raise LookupError("Application not found")
    job = session.get(Job, app.job_id)
    assert job
    candidate = load_candidate(session)
    source_signature = fingerprint(session, app_id)
    eligible_projects = {p.ref for p in candidate.projects if usable_project(p.text)}
    payload = {
        "role": job.title,
        "posting": job.description_text[:2200] + "\n" + job.description_text[-2200:],
        "experience": [
            {
                "ref": e.ref,
                "role": e.text.split("|")[:2],
                "bullets": experience_paragraphs(e.text.split("|", 2)[-1]),
            }
            for e in candidate.experience
        ],
        "projects": [
            {"ref": p.ref, "text": p.text[:450], "skills": p.skills}
            for p in candidate.projects
            if p.ref in eligible_projects
        ],
        "skills": [s.text for s in candidate.skills],
        "education": [e.text for e in candidate.education],
        "feedback": feedback,
    }
    data = json.dumps(payload)
    if len(data) > 12000:
        raise ValueError(
            "Evidence exceeds the local rewrite input limit; nothing was truncated silently."
        )
    instructions = (
        "Rewrite this candidate resume for the specific job. The summary must be 35 to 55 "
        "words, name actual supplied skills and project work, and NEVER state years of "
        "experience, leadership, revenue impact, industry experience, or B2B sales "
        "experience. Do not infer qualifications from the job description. Do not copy a "
        "requirement into candidate claims.  Return JSON only. Write a concise "
        'professional summary with concrete relevant strengths, not generic "Data '
        'professional" language. Actually rewrite sentence structure and opening verbs in '
        "at least one bullet per role, rather than copying the source. For example turn "
        "Built X using Y into Used Y to build X, retaining every fact. Rephrase "
        "experience bullets to emphasize relevant work, preserving ALL roles and each "
        "source bullet, ALL exact numbers, metrics and technologies. Use the same number "
        "of bullets per role; never merge bullets. Keep technical substance rather than "
        "shortening the resume. Remove administrative notes such as Confirm exact title "
        "and dates. Never list an unrelated project as financial reconciliation. Prefer "
        "Position Break Intelligence for finance analyst work and Real-Time Payment Fraud "
        "for engineering work when relevant. Never claim a technology in a role that does "
        "not mention it. Never invent leadership, years, qualifications, authorization, "
        "employers, achievements or metrics. Prefer 3 or 4 strongest projects using ONLY "
        "supplied refs. Select 10 to 18 most relevant skills from the exact supplied "
        "list. Explain selection briefly. Treat user feedback as wording preferences, not "
        "permission to add facts. "
    )
    result = model_call(
        session,
        settings,
        task="resume.rewrite",
        prompt_version="honest-v3",
        instructions=instructions
        + " Begin the summary with the verified role title: "
        + (candidate.experience[0].text.split("|")[0] if candidate.experience else ""),
        untrusted_text=data,
        schema=Rewrite,
        max_attempts=1,
    )
    value = Rewrite.model_validate(result.value)
    all_text = " ".join(
        x.text + " " + " ".join(x.skills)
        for group in (
            candidate.experience,
            candidate.projects,
            candidate.skills,
            candidate.education,
            candidate.other_facts,
        )
        for x in group
    )
    expected = {e.ref: e for e in candidate.experience}
    if {e.ref for e in value.experience} != set(expected) or len(value.experience) != len(expected):
        raise ValueError("Rewrite omitted or duplicated an experience. Original preserved.")
    edits = {}
    warnings = []
    unavailable = len(candidate.projects) - len(eligible_projects)
    if unavailable:
        warnings.append(
            f"{unavailable} library projects have no usable source description "
            "and were excluded from automatic selection."
        )
    summary, summary_warnings = validated_summary(
        session,
        settings,
        candidate,
        value.summary,
        all_text,
        focus_skills=role_skills(candidate, value.skills, job.title, job.description_text),
    )
    warnings.extend(summary_warnings)
    for rewritten in value.experience:
        source = expected[rewritten.ref]
        before = experience_paragraphs(source.text.split("|", 2)[-1])
        text = "\n".join(rewritten.bullets)
        try:
            validate_role(text, rewritten.bullets, source.text, before)
        except ValueError:
            # A focused second pass sees only this role's evidence and shared tools,
            # preventing project accomplishments or JD requirements leaking into it.
            from careeros.modules.agents.support import TERMS
            from careeros.modules.matching.text import contains_term

            shared = [
                t
                for t in TERMS
                if contains_term(job.description_text, t) and contains_term(source.text, t)
            ]
            try:
                focused = model_call(
                    session,
                    settings,
                    task="resume.rewrite.role",
                    prompt_version="preserve-v2",
                    instructions=(
                        "Rephrase these resume bullets. Preserve every detail, exact "
                        "number and named technology. Retain the bullet count. Change "
                        "sentence structure or opening verbs. Do not add any domain, industry, "
                        "achievement, purpose, or outcome not explicitly in these bullets. "
                        "The focus terms only affect emphasis. Return the supplied ref unchanged. "
                        "Copy numeric compounds verbatim, including hyphens. "
                        "Never insert colons into numbers. "
                        "No administrative notes."
                    ),
                    untrusted_text=json.dumps(
                        {
                            "ref": source.ref,
                            "bullets": before,
                            "focus": shared,
                            "required_number_tokens": sorted(
                                set(re.findall(r"\d[\d,.]*%?", " ".join(before)))
                            ),
                        }
                    ),
                    schema=RoleRewrite,
                    max_attempts=1,
                )
                refined = RoleRewrite.model_validate(focused.value)
                if refined.ref != source.ref:
                    raise ValueError("Role identity changed.")
                text = "\n".join(refined.bullets)
                validate_role(text, refined.bullets, source.text, before)
            except (ValueError, ModelOutputError, ModelUnavailable):
                text = "\n".join(before)
                warnings.append(
                    source.text.split("|")[1]
                    + ": kept original bullets because proposed wording failed evidence checks."
                )
        edits[source.ref] = text
    if not set(value.project_refs) <= eligible_projects:
        raise ValueError(
            "Choose projects with usable verified source descriptions; "
            "empty placeholders cannot fill a resume."
        )
    if not set(value.skills) <= {s.text for s in candidate.skills}:
        raise ValueError("Rewrite selected unverified skill evidence.")
    choices = Choices(
        summary=summary,
        experience_refs=list(expected),
        experience_edits=edits,
        project_refs=value.project_refs,
        skills=role_skills(candidate, value.skills, job.title, job.description_text),
        feedback=feedback,
    )
    session.expire_all()
    if fingerprint(session, app_id) != source_signature:
        raise ValueError("Profile or posting changed during rewriting. Request a fresh rewrite.")
    report = {
        "fingerprint": source_signature,
        "choices": choices.model_dump(),
        "rationale": "Selected projects: "
        + "; ".join(p.text.split("|")[0] for p in candidate.projects if p.ref in value.project_refs)
        + ". Skills and work history are limited to verified profile evidence. "
        "Review the wording against the job description.",
        "warnings": warnings,
        "created_at": utcnow().isoformat(),
        "provider": result.provider,
        "model": result.model,
        "before": {e.ref: e.text.split("|", 2)[-1] for e in candidate.experience},
    }
    folder = root / "documents" / app_id
    private_dir(folder)
    path = folder / "rewrite-proposal.json"
    from tempfile import NamedTemporaryFile

    with NamedTemporaryFile(mode="w", dir=folder, delete=False) as pending:
        pending.write(json.dumps(report))
        pending_path = Path(pending.name)
    pending_path.chmod(0o600)
    pending_path.replace(path)
    return report


def load(root: Path, app_id: str) -> dict[str, Any] | None:
    path = root / "documents" / app_id / "rewrite-proposal.json"
    return json.loads(path.read_text()) if path.is_file() else None


def validate_role(text: str, bullets: list[str], source: str, before: list[str]) -> None:
    from careeros.modules.agents.support import TERMS
    from careeros.modules.matching.text import contains_term

    if len(bullets) != len(before):
        raise ValueError("Source bullet count changed.")
    validate_edit(text, source)
    original_numbers = set(re.findall(r"\d[\d,.]*%?", " ".join(before)))
    if not original_numbers <= set(re.findall(r"\d[\d,.]*%?", text)):
        raise ValueError("Source metrics were omitted.")
    source_body = " ".join(before)
    for alias, canonical in (("google cloud platform", "GCP"), ("amazon web services", "AWS")):
        source_body = re.sub(alias, canonical, source_body, flags=re.I)
        text = re.sub(alias, canonical, text, flags=re.I)
    if any(contains_term(source_body, term) and not contains_term(text, term) for term in TERMS):
        raise ValueError("A source technology was omitted.")


def model_call(session: Session, settings: Settings, **kwargs: Any) -> GatewayResult:
    # Usage/cache writes get their own short transactions. A focused repair must
    # not hold a SQLite write lock throughout the next inference request.
    with Session(bind=session.get_bind()) as usage:
        try:
            return ModelGateway(settings).run(usage, **kwargs)
        finally:
            usage.commit()


def role_skills(
    candidate: Candidate, proposed: list[str], title: str, description: str
) -> list[str]:
    """Explicit verified JD tools outrank suggestions; no invented keyword stuffing."""
    from careeros.modules.matching.text import contains_term

    verified = [skill.text for skill in candidate.skills]
    requested = [skill for skill in verified if contains_term(title + " " + description, skill)]
    analyst_core = ("SQL", "Python", "Excel", "Tableau", "Power BI", "Pandas", "DuckDB")
    core = [s for s in analyst_core if s in verified] if contains_term(title, "analyst") else []
    return list(dict.fromkeys([*requested, *core, *proposed]))[:18]


def usable_project(text: str) -> bool:
    return bool(experience_paragraphs(text.split("|", 1)[-1].replace("|", "\n")))


def validated_summary(
    session: Session,
    settings: Settings,
    candidate: Candidate,
    proposed: str,
    evidence: str,
    *,
    focus_skills: list[str] | None = None,
) -> tuple[str, list[str]]:
    try:
        validate_summary(proposed, evidence, candidate)
        return proposed, []
    except ValueError:
        pass
    master = next((f.text for f in candidate.other_facts if f.kind == "master_summary"), "")
    # A repair sees candidate evidence only, never the employer's requirements or
    # its rejected wording. This prevents unsupported JD concepts being copied back.
    payload = json.dumps(
        {
            "master_summary": master,
            "verified_role_title": candidate.experience[0].text.split("|")[0]
            if candidate.experience
            else "",
            "focus_skills": focus_skills or [],
            "skills": [s.text for s in candidate.skills],
            "experience": [e.text for e in candidate.experience],
            "projects": [p.text[:400] for p in candidate.projects if usable_project(p.text)],
        }
    )
    try:
        if len(payload) > 12000:
            raise ValueError("Summary repair evidence exceeds input limit.")
        response = model_call(
            session,
            settings,
            task="resume.rewrite.summary",
            prompt_version="source-only-v2",
            instructions=(
                "Write a concise 35 to 55 word resume summary using only the supplied "
                "candidate evidence. Begin with the verified role title and prioritize the "
                "supplied focus skills. Rephrase the master summary. Do not invent years, "
                "industries, employers, qualifications, credentials, authorization or "
                "leadership. Preserve in-progress education; do not claim an unfinished degree "
                "has been earned. Do not expand scope beyond specific work shown. No new metrics."
            ),
            untrusted_text=payload,
            schema=SummaryRewrite,
            max_attempts=1,
        )
        repaired = SummaryRewrite.model_validate(response.value).summary
        validate_summary(repaired, evidence, candidate)
        return repaired, [
            "The first summary failed evidence checks; a source-only repair passed. "
            "Review its wording."
        ]
    except (ValueError, ModelUnavailable, ModelOutputError):
        if master.strip():
            validate_summary(master, evidence, candidate)
            return master, [
                "Kept your original master summary because proposed summaries "
                "failed evidence checks."
            ]
        raise ValueError(
            "Summary could not be repaired safely. Add a verified master summary "
            "or edit the draft manually."
        ) from None
