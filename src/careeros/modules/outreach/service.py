"""Draft-only outreach. Messages are stored privately; the app never sends anything."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from careeros.db.models import OutreachContact, OutreachDraft
from careeros.modules.events.service import record_event
from careeros.modules.sources.text import sha256

CHANNELS = ("email", "linkedin", "other")


class ContactIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    public_profile_url: str | None = Field(default=None, max_length=1000)
    source_url: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("public_profile_url", "source_url")
    @classmethod
    def _http(cls, v: str | None) -> str | None:
        if v and not v.startswith(("https://", "http://")):
            raise ValueError("URLs must start with http:// or https://")
        return v


class DraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: str
    recipient: str = Field(min_length=1, max_length=300)
    subject: str | None = Field(default=None, max_length=300)
    body: str = Field(min_length=1, max_length=10_000)

    @field_validator("channel")
    @classmethod
    def _channel(cls, v: str) -> str:
        if v not in CHANNELS:
            raise ValueError(f"Channel must be one of {', '.join(CHANNELS)}")
        return v


def add_contact(session: Session, company_id: str, data: ContactIn) -> OutreachContact:
    c = OutreachContact(company_id=company_id, **data.model_dump())
    session.add(c)
    session.flush()
    record_event(
        session,
        "outreach.contact_added",
        "Contact added",
        entity_type="outreach_contact",
        entity_id=c.id,
    )
    return c


def _body_path(data_dir: Path, draft_id: str) -> Path:
    folder = data_dir / "outreach"
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o700)
    return folder / f"{draft_id}.txt"


def _hash(data: DraftIn) -> str:
    return sha256(f"{data.channel}\n{data.recipient}\n{data.subject or ''}\n{data.body}")


def save_draft(
    session: Session,
    contact_id: str,
    data: DraftIn,
    data_dir: Path,
    application_id: str | None = None,
    draft_id: str | None = None,
) -> OutreachDraft:
    """Create or edit a draft. Editing changes the hash, which invalidates any approval."""
    if session.get(OutreachContact, contact_id) is None:
        raise LookupError("Contact not found")
    if draft_id:
        draft = session.get(OutreachDraft, draft_id)
        if draft is None:
            raise LookupError("Draft not found")
        if draft.status == "sent":
            raise ValueError("This message was already sent; start a new draft.")
        draft.status = "draft"
    else:
        draft = OutreachDraft(
            contact_id=contact_id,
            application_id=application_id,
            body_path="",
            payload_hash="",
            channel=data.channel,
            recipient=data.recipient,
        )
        session.add(draft)
        session.flush()
    draft.channel, draft.recipient, draft.subject = data.channel, data.recipient, data.subject
    path = _body_path(data_dir, draft.id)
    path.write_text(data.body)
    path.chmod(0o600)
    draft.body_path = str(path)
    draft.payload_hash = _hash(data)
    record_event(
        session,
        "outreach.draft_saved",
        "Outreach draft saved (not sent)",
        entity_type="outreach_draft",
        entity_id=draft.id,
    )
    return draft


def read_body(draft: OutreachDraft) -> str:
    return Path(draft.body_path).read_text()


def drafts_for_application(
    session: Session, application_id: str
) -> list[tuple[OutreachDraft, OutreachContact]]:
    stmt = (
        select(OutreachDraft, OutreachContact)
        .join(OutreachContact, OutreachContact.id == OutreachDraft.contact_id)
        .where(OutreachDraft.application_id == application_id)
        .order_by(OutreachDraft.created_at.desc())
    )
    return [(d, c) for d, c in session.execute(stmt).all()]
