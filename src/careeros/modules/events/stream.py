"""Server-Sent Events formatting for the activity stream."""

import json
from typing import Any
from zoneinfo import ZoneInfo

from careeros.db.models import ActivityEvent


def event_payload(event: ActivityEvent, display_timezone: str) -> dict[str, Any]:
    # Only safe, non-sensitive fields go to the browser (no metadata blobs).
    return {
        "id": event.id,
        "event_type": event.event_type,
        "message": event.message,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "created_at": event.created_at.isoformat(),
        "created_local": event.created_at.astimezone(ZoneInfo(display_timezone)).strftime(
            "%Y-%m-%d %H:%M %Z"
        ),
    }


def format_sse(event: ActivityEvent, display_timezone: str) -> str:
    data = json.dumps(event_payload(event, display_timezone))
    return f"id: {event.id}\nevent: activity\ndata: {data}\n\n"


HEARTBEAT = ": heartbeat\n\n"
RETRY = "retry: 3000\n\n"
