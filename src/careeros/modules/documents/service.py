"""Generate, version, diff and acknowledge application documents."""

import difflib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import (
    Application,
    Company,
    Document,
    DocumentClaim,
    Job,
    RoleLane,
)
from careeros.modules.documents.content import (
    Candidate,
    DocumentContent,
    SourceItem,
    build_cover_letter,
    build_resume,
)
from careeros.modules.documents.qa import Finding, run_qa, status_for
from careeros.modules.documents.render import render_docx
from careeros.modules.events.service import record_event
from careeros.modules.profile import service as profile_service
from careeros.modules.sources.text import sha256

DocType = Literal["resume", "cover_letter"]
DOC_LABELS = {"resume": "Resume", "cover_letter": "Cover letter"}


class DocumentError(ValueError):
    pass


def load_candidate(session: Session) -> Candidate:
    profile = profile_service.get_profile(session)
    if profile is None:
        raise DocumentError("Create your profile first.")
    pid = profile.id
    facts = profile_service.list_facts(session, pid)
    skills = profile_service.list_skills(session, pid)
    exps = profile_service.list_experience(session, pid)
    projs = profile_service.list_projects(session, pid)
    v = "verified"
    unverified = (
        sum(f.verified_status != v for f in facts)
        + sum(s.verified_status != v for s in skills)
        + sum(e.verified_status != v for e in exps)
        + sum(p.verified_status != v for p in projs)
    )
    return Candidate(
        profile_ref=f"profile:{pid}",
        name=profile.display_name or "",
        location=profile.current_location,
        email=profile.email,
        phone=profile.phone,
        education=tuple(
            SourceItem(f"fact:{f.id}", "fact", f.fact_value)
            for f in facts
            if f.verified_status == v and f.category == "education"
        ),
        other_facts=tuple(
            SourceItem(f"fact:{f.id}", "fact", f.fact_value)
            for f in facts
            if f.verified_status == v and f.category != "education"
        ),
        skills=tuple(
            SourceItem(f"skill:{s.skill_id}", "skill", s.name)
            for s in skills
            if s.verified_status == v
        ),
        experience=tuple(
            SourceItem(
                f"experience:{e.id}",
                "experience",
                f"{e.title}|{e.organization}|{e.description or ''}",
                start=e.start_date,
                end=e.end_date,
            )
            for e in exps
            if e.verified_status == v
        ),
        projects=tuple(
            SourceItem(
                f"project:{p.id}",
                "project",
                f"{p.name}|{p.description or ''}|" + "\n".join(p.outcomes_json),
                skills=tuple(p.technologies_json),
            )
            for p in projs
            if p.verified_status == v
        ),
        excluded_unverified=unverified,
    )


def documents_dir(data_dir: Path, application_id: str) -> Path:
    path = data_dir / "documents" / application_id
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def latest(session: Session, application_id: str, doc_type: str) -> Document | None:
    stmt = (
        select(Document)
        .where(Document.application_id == application_id, Document.document_type == doc_type)
        .order_by(Document.version.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def generate(session: Session, application_id: str, doc_type: DocType, data_dir: Path) -> Document:
    """Create a new immutable version. Returns the existing latest one if nothing changed."""
    if doc_type not in DOC_LABELS:
        raise DocumentError("Unknown document type")
    app = session.get(Application, application_id)
    if app is None:
        raise LookupError("Application not found")
    job = session.get(Job, app.job_id)
    assert job is not None
    company = session.get(Company, job.company_id)
    assert company is not None
    lane = session.get(RoleLane, app.role_lane_id) if app.role_lane_id else None
    lane_name = lane.name if lane else "General"
    candidate = load_candidate(session)
    builder = build_resume if doc_type == "resume" else build_cover_letter
    content = builder(candidate, job.title, company.canonical_name, job.description_text, lane_name)
    findings = run_qa(content, candidate, utcnow().date())
    payload = json.dumps(content.to_dict(), sort_keys=True)
    content_hash = sha256(payload)

    current = latest(session, application_id, doc_type)
    if current is not None and current.content_hash == content_hash:
        return current
    version = (current.version + 1) if current else 1
    folder = documents_dir(data_dir, application_id)
    stem = f"{doc_type}-v{version}"
    json_path = folder / f"{stem}.json"
    json_path.write_text(payload)
    json_path.chmod(0o600)
    render_docx(content, folder / f"{stem}.docx")
    doc = Document(
        application_id=application_id,
        document_type=doc_type,
        version=version,
        storage_path=str(folder / f"{stem}.docx"),
        content_hash=content_hash,
        base_template_id=lane_name,
        model_provider="none",
        status=status_for(findings, False),
        qa_json=[f.to_dict() for f in findings],
    )
    session.add(doc)
    session.flush()
    flagged = {f.claim: f.message for f in findings if f.claim}
    for claim in content.claims():
        session.add(
            DocumentClaim(
                document_id=doc.id,
                section=claim.section,
                claim_text=claim.text,
                supporting_profile_fact_ids_json=claim.refs,
                verification_status="unsupported" if claim.text in flagged else "supported",
                warning=flagged.get(claim.text),
            )
        )
    record_event(
        session,
        "document.generated",
        f"{DOC_LABELS[doc_type]} v{version} generated: {doc.status.replace('_', ' ')}",
        entity_type="document",
        entity_id=doc.id,
        metadata={
            "errors": sum(f.severity == "error" for f in findings),
            "warnings": sum(f.severity == "warning" for f in findings),
        },
    )
    return doc


def load_content(doc: Document) -> DocumentContent:
    path = Path(doc.storage_path).with_suffix(".json")
    data = path.read_text()
    if sha256(data) != doc.content_hash:
        raise DocumentError("Stored document no longer matches its recorded hash.")
    return DocumentContent.from_dict(json.loads(data))


def findings(doc: Document) -> list[Finding]:
    return [Finding(**f) for f in doc.qa_json]


def acknowledge(session: Session, document_id: str) -> Document:
    doc = session.get(Document, document_id)
    if doc is None:
        raise LookupError("Document not found")
    if doc.status == "blocked":
        raise DocumentError("This version has errors. Fix your profile and regenerate.")
    doc.warnings_acknowledged_at = utcnow()
    doc.status = status_for(findings(doc), True)
    record_event(
        session,
        "document.acknowledged",
        f"{DOC_LABELS.get(doc.document_type, doc.document_type)} v{doc.version} "
        "warnings acknowledged",
        entity_type="document",
        entity_id=doc.id,
    )
    return doc


def diff(session: Session, document_id: str) -> tuple[Document | None, list[str]]:
    doc = session.get(Document, document_id)
    if doc is None:
        raise LookupError("Document not found")
    prev = session.scalars(
        select(Document).where(
            Document.application_id == doc.application_id,
            Document.document_type == doc.document_type,
            Document.version == doc.version - 1,
        )
    ).first()
    new_text = load_content(doc).as_text().splitlines()
    old_text = load_content(prev).as_text().splitlines() if prev else []
    lines = list(
        difflib.unified_diff(
            old_text,
            new_text,
            f"v{prev.version}" if prev else "(none)",
            f"v{doc.version}",
            lineterm="",
            n=2,
        )
    )
    return prev, lines


@dataclass
class DocSet:
    resume: Document | None
    cover_letter: Document | None
    history: list[Document]


def documents_for(session: Session, application_id: str) -> DocSet:
    history = list(
        session.scalars(
            select(Document)
            .where(Document.application_id == application_id)
            .order_by(Document.document_type, Document.version.desc())
        )
    )
    return DocSet(
        latest(session, application_id, "resume"),
        latest(session, application_id, "cover_letter"),
        history,
    )


def claims_for(session: Session, document_id: str) -> list[DocumentClaim]:
    return list(
        session.scalars(select(DocumentClaim).where(DocumentClaim.document_id == document_id))
    )


def document_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(Document)) or 0)
