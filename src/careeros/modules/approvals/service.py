"""The single approval gate for every external action.

An approval binds the action type, the exact target and destination, and a
hash of the exact payload (document hashes or message text). It expires, is
single-use, and is invalidated the moment the payload changes. Nothing here
performs an external action: the user does, then confirms it.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.common.fs import private_dir
from careeros.db.models import (
    Application,
    Approval,
    Company,
    Document,
    FollowUp,
    Job,
    JobSourceRecord,
    OutreachDraft,
)
from careeros.modules.events.service import record_event
from careeros.modules.sources.text import sha256

ActionType = Literal["submit_application", "send_outreach"]
APPROVAL_TTL = timedelta(hours=72)
FOLLOW_UP_AFTER = timedelta(days=7)
ACTION_LABELS = {"submit_application": "Submit application", "send_outreach": "Send message"}


class ApprovalError(ValueError):
    pass


@dataclass
class Payload:
    action_type: ActionType
    target_type: str
    target_id: str
    destination: str
    data: dict[str, Any]

    @property
    def canonical(self) -> str:
        return json.dumps(
            {
                "action": self.action_type,
                "target": [self.target_type, self.target_id],
                "destination": self.destination,
                "data": self.data,
            },
            sort_keys=True,
        )

    @property
    def hash(self) -> str:
        return sha256(self.canonical)


def _latest(session: Session, app_id: str, doc_type: str) -> Document | None:
    stmt = (
        select(Document)
        .where(Document.application_id == app_id, Document.document_type == doc_type)
        .order_by(Document.version.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def application_payload(session: Session, app_id: str, include_cover_letter: bool) -> Payload:
    app = session.get(Application, app_id)
    if app is None:
        raise LookupError("Application not found")
    job = session.get(Job, app.job_id)
    assert job is not None
    company = session.get(Company, job.company_id)
    assert company is not None
    url = (
        session.scalars(
            select(JobSourceRecord.source_url)
            .where(JobSourceRecord.job_id == job.id)
            .order_by(JobSourceRecord.first_seen_at)
        ).first()
        or job.canonical_url
    )
    resume = _latest(session, app_id, "resume")
    if resume is None or resume.status != "ready":
        raise ApprovalError("The latest resume must pass QA (and warnings be acknowledged) first.")
    docs = [{"type": "resume", "version": resume.version, "hash": resume.content_hash}]
    if include_cover_letter:
        letter = _latest(session, app_id, "cover_letter")
        if letter is None or letter.status != "ready":
            raise ApprovalError("The latest cover letter must pass QA first, or leave it out.")
        docs.append(
            {"type": "cover_letter", "version": letter.version, "hash": letter.content_hash}
        )
    return Payload(
        "submit_application",
        "application",
        app_id,
        url,
        {"job_title": job.title, "company": company.canonical_name, "documents": docs},
    )


def outreach_payload(session: Session, draft_id: str) -> Payload:
    draft = session.get(OutreachDraft, draft_id)
    if draft is None:
        raise LookupError("Draft not found")
    if draft.status in ("sent", "archived"):
        raise ApprovalError(f"This draft is already {draft.status}.")
    return Payload(
        "send_outreach",
        "outreach_draft",
        draft_id,
        f"{draft.channel}:{draft.recipient}",
        {"subject": draft.subject, "body_hash": draft.payload_hash},
    )


def current_payload(session: Session, approval: Approval) -> Payload | None:
    """Recompute the payload for an approval's target, or None if it no longer qualifies."""
    try:
        if approval.action_type == "submit_application":
            snap = snapshot(approval)
            with_letter = any(d["type"] == "cover_letter" for d in snap["data"]["documents"])
            return application_payload(session, approval.target_id, with_letter)
        return outreach_payload(session, approval.target_id)
    except (ApprovalError, LookupError):
        return None


def _approvals_dir(data_dir: Path) -> Path:
    path = data_dir / "approvals"
    private_dir(path)
    return path


def snapshot(approval: Approval) -> dict[str, Any]:
    data = Path(approval.payload_snapshot_path).read_text()
    if sha256(data) != approval.payload_hash:
        raise ApprovalError("Approval snapshot doesn't match its hash.")
    parsed: dict[str, Any] = json.loads(data)
    return parsed


def _supersede(session: Session, target_type: str, target_id: str) -> None:
    for old in session.scalars(
        select(Approval).where(
            Approval.target_type == target_type,
            Approval.target_id == target_id,
            Approval.status.in_(("pending", "approved")),
        )
    ):
        old.status = "invalidated"
        old.decision_note = "Superseded by a newer approval request."
        old.decided_at = utcnow()


def request(session: Session, payload: Payload, data_dir: Path) -> Approval:
    _supersede(session, payload.target_type, payload.target_id)
    approval = Approval(
        action_type=payload.action_type,
        target_type=payload.target_type,
        target_id=payload.target_id,
        destination=payload.destination,
        payload_hash=payload.hash,
        payload_snapshot_path="",
        expires_at=utcnow() + APPROVAL_TTL,
    )
    session.add(approval)
    session.flush()
    path = _approvals_dir(data_dir) / f"{approval.id}.json"
    path.write_text(payload.canonical)
    path.chmod(0o600)
    approval.payload_snapshot_path = str(path)
    record_event(
        session,
        "approval.created",
        f"Approval requested: {ACTION_LABELS[payload.action_type]}",
        entity_type="approval",
        entity_id=approval.id,
    )
    return approval


def refresh(session: Session, approval: Approval, now: datetime | None = None) -> Approval:
    """Expire or invalidate an open approval whose time ran out or payload changed."""
    if approval.status not in ("pending", "approved"):
        return approval
    now = now or utcnow()
    if approval.expires_at <= now:
        approval.status = "expired"
        approval.decided_at = now
        record_event(
            session,
            "approval.expired",
            "Approval expired; request a new one.",
            entity_type="approval",
            entity_id=approval.id,
        )
        return approval
    current = current_payload(session, approval)
    if current is None or current.hash != approval.payload_hash:
        approval.status = "invalidated"
        approval.decided_at = now
        approval.decision_note = "The package changed after this approval was requested."
        record_event(
            session,
            "approval.invalidated",
            "Approval invalidated: the package changed. Review and approve again.",
            entity_type="approval",
            entity_id=approval.id,
        )
    return approval


def _get_open(session: Session, approval_id: str, expected: str) -> Approval:
    approval = session.get(Approval, approval_id)
    if approval is None:
        raise LookupError("Approval not found")
    refresh(session, approval)
    if approval.status != expected:
        raise ApprovalError(f"This approval is {approval.status}, not {expected}.")
    return approval


def decide(
    session: Session, approval_id: str, approve: bool, *, confirmed: bool, note: str | None = None
) -> Approval:
    approval = _get_open(session, approval_id, "pending")
    if approve and not confirmed:
        raise ApprovalError("Tick the confirmation box to approve this exact package.")
    approval.status = "approved" if approve else "rejected"
    approval.decided_at = utcnow()
    approval.decision_note = (note or "").strip()[:1000] or None
    record_event(
        session,
        "approval.decided",
        f"{ACTION_LABELS[approval.action_type]} {approval.status}",
        entity_type="approval",
        entity_id=approval.id,
    )
    return approval


def confirm_done(
    session: Session, approval_id: str, *, confirmed: bool, when: datetime | None = None
) -> Approval:
    """Record that the user performed the approved action themselves. Single-use."""
    approval = _get_open(session, approval_id, "approved")
    if not confirmed:
        raise ApprovalError("Confirm that you completed this yourself, exactly as approved.")
    now = utcnow()
    done_at = when or now
    if done_at > now + timedelta(minutes=5):
        raise ApprovalError("The completion time can't be in the future.")
    approval.status = "used"
    approval.used_at = now
    if approval.action_type == "submit_application":
        from careeros.modules.applications import service as apps

        app = session.get(Application, approval.target_id)
        assert app is not None
        apps.set_status(
            session,
            app.id,
            "submitted",
            f"Submitted by you (approval {approval.id[:8]})",
            system=True,
        )
        app.submitted_at = done_at
        add_follow_up(
            session,
            app.id,
            done_at + FOLLOW_UP_AFTER,
            "check_status",
            "No response yet? Check the portal or follow up.",
        )
    else:
        draft = session.get(OutreachDraft, approval.target_id)
        assert draft is not None
        draft.status = "sent"
    record_event(
        session,
        "approval.used",
        f"{ACTION_LABELS[approval.action_type]}: done by you",
        entity_type="approval",
        entity_id=approval.id,
    )
    return approval


# ---------- follow-ups ----------


def add_follow_up(
    session: Session,
    application_id: str,
    due_at: datetime,
    action_type: str,
    notes: str | None = None,
    contact_id: str | None = None,
) -> FollowUp:
    if session.get(Application, application_id) is None:
        raise LookupError("Application not found")
    fu = FollowUp(
        application_id=application_id,
        due_at=due_at,
        action_type=action_type[:40],
        notes=(notes or "")[:1000] or None,
        contact_id=contact_id,
    )
    session.add(fu)
    session.flush()
    _sync_next(session, application_id)
    record_event(
        session,
        "follow_up.created",
        f"Follow-up due {due_at.date().isoformat()}",
        entity_type="follow_up",
        entity_id=fu.id,
    )
    return fu


def close_follow_up(
    session: Session, follow_up_id: str, status: Literal["done", "skipped"]
) -> FollowUp:
    fu = session.get(FollowUp, follow_up_id)
    if fu is None:
        raise LookupError("Follow-up not found")
    if status not in ("done", "skipped"):
        raise ApprovalError("Unknown follow-up status")
    fu.status = status
    fu.completed_at = utcnow()
    session.flush()
    _sync_next(session, fu.application_id)
    return fu


def _sync_next(session: Session, application_id: str) -> None:
    app = session.get(Application, application_id)
    if app is None:
        return
    nxt = session.scalars(
        select(FollowUp.due_at)
        .where(FollowUp.application_id == application_id, FollowUp.status == "open")
        .order_by(FollowUp.due_at)
        .limit(1)
    ).first()
    app.next_follow_up_at = nxt


@dataclass
class FollowUpRow:
    follow_up: FollowUp
    job_title: str
    company: str
    overdue: bool


def open_follow_ups(session: Session, *, due_within_days: int | None = None) -> list[FollowUpRow]:
    now = utcnow()
    stmt = (
        select(FollowUp, Job.title, Company.canonical_name)
        .join(Application, Application.id == FollowUp.application_id)
        .join(Job, Job.id == Application.job_id)
        .join(Company, Company.id == Job.company_id)
        .where(FollowUp.status == "open")
        .order_by(FollowUp.due_at)
    )
    if due_within_days is not None:
        stmt = stmt.where(FollowUp.due_at <= now + timedelta(days=due_within_days))
    return [FollowUpRow(f, t, c, f.due_at < now) for f, t, c in session.execute(stmt).all()]


def list_approvals(session: Session, status: str | None = None) -> list[Approval]:
    stmt = select(Approval).order_by(Approval.requested_at.desc())
    rows = list(session.scalars(stmt))
    for a in rows:
        refresh(session, a)
    return [a for a in rows if status is None or a.status == status]
