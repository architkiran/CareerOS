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
from careeros.modules.documents.content import experience_paragraphs
from careeros.modules.documents.service import load_candidate
from careeros.modules.documents.workbench import Choices, validate_edit
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
            {"ref": p.ref, "text": p.text[:450], "skills": p.skills} for p in candidate.projects
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
    validate_edit(value.summary, all_text)
    expected = {e.ref: e for e in candidate.experience}
    if {e.ref for e in value.experience} != set(expected) or len(value.experience) != len(expected):
        raise ValueError("Rewrite omitted or duplicated an experience. Original preserved.")
    edits = {}
    warnings = []
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
    if not set(value.project_refs) <= {p.ref for p in candidate.projects} or not set(
        value.skills
    ) <= {s.text for s in candidate.skills}:
        raise ValueError("Rewrite selected unverified project or skill evidence.")
    choices = Choices(
        summary=value.summary,
        experience_refs=list(expected),
        experience_edits=edits,
        project_refs=value.project_refs,
        skills=value.skills,
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
