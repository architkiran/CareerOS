"""Application records: user-reported manual applications and optional package approvals."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import Application, ApplicationEvent, Company, Job
from careeros.modules.events.service import record_event

STATUSES = (
    "preparing",
    "ready",
    "submitted",
    "response",
    "screen",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
)
# Manual moves the user can make. "submitted" is set only by confirming an approved submission.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "preparing": ("withdrawn",),
    "ready": ("preparing", "withdrawn"),
    "submitted": ("response", "screen", "interview", "offer", "rejected", "withdrawn"),
    "response": ("screen", "interview", "offer", "rejected", "withdrawn"),
    "screen": ("interview", "offer", "rejected", "withdrawn"),
    "interview": ("interview", "offer", "rejected", "withdrawn"),
    "offer": ("withdrawn",),
    "rejected": (),
    "withdrawn": ("preparing",),
}


class ApplicationError(ValueError):
    pass


def get_for_job(session: Session, job_id: str) -> Application | None:
    return session.scalars(select(Application).where(Application.job_id == job_id)).first()


def start_application(session: Session, job_id: str) -> Application:
    existing = get_for_job(session, job_id)
    if existing is not None:
        return existing
    job = session.get(Job, job_id)
    if job is None:
        raise LookupError("Job not found")
    from careeros.modules.matching.service import matches_for_job

    views = matches_for_job(session, job_id)
    lane_id = views[0].lane_id if views and views[0].match.classified else None
    app = Application(job_id=job_id, role_lane_id=lane_id)
    session.add(app)
    session.flush()
    log(session, app, "created", "Application started")
    record_event(
        session,
        "application.created",
        f"Application started: {job.title}",
        entity_type="application",
        entity_id=app.id,
    )
    return app


def log(
    session: Session,
    app: Application,
    event_type: str,
    notes: str | None = None,
    source: str = "user",
    occurred_at: datetime | None = None,
) -> ApplicationEvent:
    ev = ApplicationEvent(
        application_id=app.id,
        event_type=event_type,
        notes=notes,
        source=source,
        occurred_at=occurred_at or utcnow(),
    )
    session.add(ev)
    return ev


def set_status(
    session: Session,
    application_id: str,
    status: str,
    notes: str | None = None,
    *,
    system: bool = False,
) -> Application:
    app = session.get(Application, application_id)
    if app is None:
        raise LookupError("Application not found")
    if status not in STATUSES:
        raise ApplicationError(f"Unknown status {status!r}")
    if not system and status not in TRANSITIONS[app.status]:
        raise ApplicationError(f"Can't move from {app.status} to {status}.")
    previous = app.status
    app.status = status
    if status in ("offer", "rejected", "withdrawn"):
        app.outcome = status
    log(session, app, f"status:{status}", notes, source="system" if system else "user")
    record_event(
        session,
        "application.status_changed",
        f"Application {previous} → {status}",
        entity_type="application",
        entity_id=app.id,
    )
    return app


def sync_ready(session: Session, app: Application, docs_ready: bool) -> None:
    """Move between preparing and ready as the latest resume passes or fails QA."""
    if app.status == "preparing" and docs_ready:
        set_status(session, app.id, "ready", "Latest resume passed QA", system=True)
    elif app.status == "ready" and not docs_ready:
        set_status(session, app.id, "preparing", "Latest resume needs attention", system=True)


@dataclass
class AppRow:
    app: Application
    job: Job
    company: str


def list_applications(session: Session, status: str | None = None) -> list[AppRow]:
    stmt = (
        select(Application, Job, Company.canonical_name)
        .join(Job, Job.id == Application.job_id)
        .join(Company, Company.id == Job.company_id)
        .order_by(Application.updated_at.desc())
    )
    if status:
        stmt = stmt.where(Application.status == status)
    return [AppRow(a, j, c) for a, j, c in session.execute(stmt).all()]


def history(session: Session, application_id: str) -> list[ApplicationEvent]:
    stmt = (
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == application_id)
        .order_by(ApplicationEvent.occurred_at.desc())
    )
    return list(session.scalars(stmt))


def record_manual_application(
    session: Session,
    job_id: str,
    *,
    confirmed: bool,
    applied_at: datetime | None = None,
    notes: str | None = None,
) -> Application:
    """Record an external action the user says they already completed. Never submits."""
    if not confirmed:
        raise ApplicationError("Confirm that you already applied on the employer’s website.")
    when = applied_at or utcnow()
    if when.tzinfo is None or when > utcnow():
        raise ApplicationError("Application date must be timezone-aware and not in the future.")
    if notes and len(notes) > 3000:
        raise ApplicationError("Application notes must be 3000 characters or fewer.")
    app = start_application(session, job_id)
    # Double clicks and retries preserve the original user record and later outcomes.
    if app.submitted_at is not None:
        return app
    if app.status not in ("preparing", "ready", "withdrawn"):
        raise ApplicationError("This application already has an outcome; review its record.")
    previous = app.status
    app.status, app.submitted_at = "submitted", when
    app.outcome = None
    app.notes = notes if notes is not None else app.notes
    log(
        session,
        app,
        "status:submitted",
        "User confirmed a manually completed application.",
        source="user_manual",
        occurred_at=when,
    )
    from careeros.modules.matching.service import best_matches

    match = best_matches(session, [job_id]).get(job_id)
    record_event(
        session,
        "application.manually_recorded",
        f"User recorded {previous} → applied",
        entity_type="application",
        entity_id=app.id,
        metadata={"job_id": job_id, "match_score": match.effective_score if match else None},
    )
    return app
