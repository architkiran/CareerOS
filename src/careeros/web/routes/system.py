from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.exc import SQLAlchemyError

from careeros.db.models import ActivityEvent
from careeros.modules.events.service import latest_events
from careeros.modules.system.overview import Overview, build_overview
from careeros.modules.system.status import get_system_status

router = APIRouter()


@router.get("/health")
def health(request: Request) -> JSONResponse:
    state = request.app.state
    status = get_system_status(state.settings, state.engine)
    code = 503 if status.status == "error" else 200
    return JSONResponse(status.to_dict(), status_code=code)


@router.get("/")
def home(queued: str | None = None) -> RedirectResponse:
    suffix = (
        "?refresh=already" if queued == "already" else "?refresh=queued" if queued == "1" else ""
    )
    return RedirectResponse("/new-jobs" + suffix, 303)


@router.get("/advanced/system", response_class=HTMLResponse)
def dashboard(request: Request, queued: str | None = None) -> HTMLResponse:
    state = request.app.state
    status = get_system_status(state.settings, state.engine)
    events: list[ActivityEvent] = []
    overview: Overview | None = None
    events_error: str | None = None
    if status.schema.up_to_date:
        try:
            with state.session_factory() as session:
                events = latest_events(session)
                overview = build_overview(session, state.settings)
        except SQLAlchemyError:
            events_error = "Could not load dashboard data."
    cursor = events[0].id if events else 0
    spent = 0.0
    if status.schema.up_to_date:
        from careeros.modules.models.gateway import usage_summary

        with state.session_factory() as session:
            spent = usage_summary(session).spent_30d
    response: HTMLResponse = state.templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "status": status,
            "events": events,
            "events_error": events_error,
            "ov": overview,
            "cursor": cursor,
            "queued": queued,
            "spent": spent,
        },
    )
    return response
