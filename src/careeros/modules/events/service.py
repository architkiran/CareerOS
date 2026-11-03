"""Append-only activity events for the dashboard feed.

Messages and metadata must never contain secrets, work-authorization values,
full resumes, or other sensitive personal data. Use ids and counts.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from careeros.db.models import ActivityEvent


def record_event(
    session: Session,
    event_type: str,
    message: str,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ActivityEvent:
    event = ActivityEvent(
        event_type=event_type,
        message=message,
        entity_type=entity_type,
        entity_id=entity_id,
        metadata_json=metadata or {},
    )
    session.add(event)
    return event


def events_after(session: Session, cursor: int, limit: int = 100) -> list[ActivityEvent]:
    stmt = (
        select(ActivityEvent)
        .where(ActivityEvent.id > cursor)
        .order_by(ActivityEvent.id.asc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def latest_events(session: Session, limit: int = 20) -> list[ActivityEvent]:
    stmt = select(ActivityEvent).order_by(ActivityEvent.id.desc()).limit(limit)
    return list(session.scalars(stmt))
