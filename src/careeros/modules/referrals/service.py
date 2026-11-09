"""Company-scoped referral research and draft-only requests backed by the verified profile."""

from dataclasses import dataclass
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from careeros.db.models import Company, Job, OutreachContact, OutreachDraft, ReferralPath
from careeros.modules.documents.service import load_candidate
from careeros.modules.documents.tailoring import relevance
from careeros.modules.events.service import record_event
from careeros.modules.outreach import service as outreach

RELATIONSHIPS = {
    "known": "Someone I know",
    "introduction": "Introduction through someone I know",
    "alumni": "Alumni connection I found",
    "research": "Employee I’m researching",
}
STATUSES = {
    "identified": "Identified",
    "contacted": "I contacted them",
    "replied": "They replied",
    "requested": "I requested a referral",
    "referred": "Referral confirmed by contact",
    "declined": "Declined / closed",
}


class PathIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relationship: str = "research"
    via: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("relationship")
    @classmethod
    def _relationship(cls, value: str) -> str:
        if value not in RELATIONSHIPS:
            raise ValueError("Choose a supported relationship")
        return value


def overview(session: Session) -> dict[str, int]:
    return {
        "contacts": session.scalar(select(func.count()).select_from(OutreachContact)) or 0,
        "active": session.scalar(
            select(func.count())
            .select_from(ReferralPath)
            .where(ReferralPath.status.not_in(("referred", "declined")))
        )
        or 0,
    }


def search_links(company: str, title: str) -> list[dict[str, str]]:
    return [
        {
            "label": "BU alumni at this employer",
            "hint": "Research profiles; verify current employment.",
            "url": "https://www.linkedin.com/search/results/people/?"
            + urlencode({"keywords": f'{company} "Boston University"'}),
        },
        {
            "label": "Employees on the relevant team",
            "hint": "Use LinkedIn’s connection filters to look for mutual contacts.",
            "url": "https://www.linkedin.com/search/results/people/?"
            + urlencode({"keywords": f"{company} {title}"}),
        },
        {
            "label": "Public posts offering referrals",
            "hint": "Search results are leads, not proof someone will refer you.",
            "url": "https://www.google.com/search?"
            + urlencode(
                {"q": f'"{company}" ("happy to refer" OR "referral") site:linkedin.com/posts'}
            ),
        },
        {
            "label": "BU Connects directory",
            "hint": "BU’s official networking directory. Sign in yourself; search by employer.",
            "url": "https://www.bu.edu/alumni/career/buconnects/",
        },
    ]


def save_path(session: Session, job_id: str, contact_id: str, data: PathIn) -> ReferralPath:
    job, contact = session.get(Job, job_id), session.get(OutreachContact, contact_id)
    if job is None or contact is None:
        raise LookupError("Role or contact not found")
    if job.company_id != contact.company_id:
        raise ValueError("The contact must belong to this employer")
    path = session.scalar(
        select(ReferralPath).where(
            ReferralPath.job_id == job_id, ReferralPath.contact_id == contact_id
        )
    )
    if path is None:
        path = ReferralPath(job_id=job_id, contact_id=contact_id)
        session.add(path)
    path.relationship, path.via, path.notes = data.relationship, data.via, data.notes
    session.flush()
    record_event(
        session,
        "referral.path_saved",
        "Referral path saved; no message sent.",
        entity_type="referral_path",
        entity_id=path.id,
    )
    return path


def set_status(session: Session, path_id: str, status: str) -> ReferralPath:
    path = session.get(ReferralPath, path_id)
    if path is None:
        raise LookupError("Referral path not found")
    if status not in STATUSES:
        raise ValueError("Choose a supported referral status")
    path.status = status
    record_event(
        session,
        "referral.status_recorded",
        f"User recorded: {STATUSES[status]}",
        entity_type="referral_path",
        entity_id=path.id,
    )
    return path


@dataclass(frozen=True)
class RequestText:
    subject: str
    body: str


def request_text(session: Session, path: ReferralPath) -> RequestText:
    job = session.get(Job, path.job_id)
    contact = session.get(OutreachContact, path.contact_id)
    assert job and contact
    company = session.get(Company, job.company_id)
    assert company
    candidate = load_candidate(session)
    projects = sorted(
        candidate.projects, key=lambda p: -relevance(p, job.title + " " + job.description_text)
    )
    evidence = f"My work includes {projects[0].text.split('|')[0].strip()}.\n\n" if projects else ""
    body = (
        f"Hi {contact.name},\n\nI’m interested in the {job.title} role "
        f"at {company.canonical_name}.\n"
        f"{job.canonical_url}\n\n{evidence}"
        "Would you be open to a brief conversation about the team? If you think my background "
        "could be a fit, would you feel comfortable referring me, "
        "or pointing me to the right person? "
        "Happy to share my resume and a short project overview.\n\n"
        f"Thank you,\n{candidate.name}"
    )
    return RequestText(f"Question about {job.title} at {company.canonical_name}", body)


def contacts_for(session: Session, company_id: str) -> list[OutreachContact]:
    return list(
        session.scalars(
            select(OutreachContact)
            .where(OutreachContact.company_id == company_id)
            .order_by(OutreachContact.name)
        )
    )


def paths_for(
    session: Session, job_id: str
) -> list[tuple[ReferralPath, OutreachContact, OutreachDraft | None, str | None]]:
    rows = session.execute(
        select(ReferralPath, OutreachContact, OutreachDraft)
        .join(OutreachContact, OutreachContact.id == ReferralPath.contact_id)
        .outerjoin(OutreachDraft, OutreachDraft.id == ReferralPath.draft_id)
        .where(ReferralPath.job_id == job_id)
        .order_by(ReferralPath.updated_at.desc())
    ).all()
    result: list[tuple[ReferralPath, OutreachContact, OutreachDraft | None, str | None]] = []
    for path, contact, draft in rows:
        try:
            body = outreach.read_body(draft) if draft else None
        except OSError:
            body = None
        result.append((path, contact, draft, body))
    return result
