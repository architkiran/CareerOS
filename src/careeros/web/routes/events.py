import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select

from careeros.db.models import ActivityEvent
from careeros.modules.events.service import events_after
from careeros.modules.events.stream import HEARTBEAT, RETRY, event_payload, format_sse

router = APIRouter()
POLL_INTERVAL_SECONDS = 1.0


def _latest_id(request: Request) -> int:
    with request.app.state.session_factory() as s:
        return int(s.scalar(select(func.max(ActivityEvent.id))) or 0)


def _resolve_cursor(request: Request, after: int | None) -> int:
    header = request.headers.get("last-event-id")
    if header and header.isdigit():
        return int(header)
    if after is not None:
        return after
    return _latest_id(request)


def _fetch(request: Request, cursor: int) -> list[ActivityEvent]:
    with request.app.state.session_factory() as s:
        return events_after(s, cursor, limit=100)


@router.get("/events/stream")
async def stream(
    request: Request, after: int | None = Query(default=None, ge=0)
) -> StreamingResponse:
    cursor = _resolve_cursor(request, after)
    settings = request.app.state.settings
    tz = settings.display_timezone
    heartbeat_every = settings.sse_heartbeat_seconds
    max_seconds: float | None = getattr(request.app.state, "sse_max_seconds", None)

    async def gen() -> AsyncIterator[str]:
        nonlocal cursor
        started = last_beat = time.monotonic()
        yield RETRY
        while True:
            if await request.is_disconnected():
                return
            events = await run_in_threadpool(_fetch, request, cursor)
            for event in events:
                cursor = event.id
                yield format_sse(event, tz)
            now = time.monotonic()
            if now - last_beat >= heartbeat_every:
                last_beat = now
                yield HEARTBEAT
            if max_seconds is not None and now - started >= max_seconds:
                return
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/events/feed")
def feed(request: Request, after: int = Query(default=0, ge=0)) -> JSONResponse:
    """Polling fallback for browsers or proxies where SSE doesn't work."""
    tz = request.app.state.settings.display_timezone
    events: list[dict[str, Any]] = [event_payload(e, tz) for e in _fetch(request, after)]
    return JSONResponse({"events": events}, headers={"Cache-Control": "no-store"})
