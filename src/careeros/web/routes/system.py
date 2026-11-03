from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from careeros.db.models import ActivityEvent
from careeros.modules.system.status import get_system_status, recent_events

router = APIRouter()


@router.get("/health")
def health(request: Request) -> JSONResponse:
    state = request.app.state
    status = get_system_status(state.settings, state.engine)
    code = 503 if status.status == "error" else 200
    return JSONResponse(status.to_dict(), status_code=code)


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    state = request.app.state
    status = get_system_status(state.settings, state.engine)
    events: list[ActivityEvent] = []
    events_error: str | None = None
    if status.schema.up_to_date:
        try:
            with state.session_factory() as session:
                events = recent_events(session)
        except SQLAlchemyError:
            events_error = "Could not load recent activity."
    response: HTMLResponse = state.templates.TemplateResponse(
        request,
        "dashboard.html",
        {"status": status, "events": events, "events_error": events_error},
    )
    return response
