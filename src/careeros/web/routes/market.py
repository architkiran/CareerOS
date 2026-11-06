from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from careeros.db.models import MarketBrief
from careeros.modules.market.contracts import MarketReport
from careeros.modules.market.service import generate_brief, latest_brief
from careeros.modules.system.status import get_system_status
from careeros.web.csrf import verify_csrf
from careeros.web.deps import get_session

router = APIRouter(dependencies=[Depends(verify_csrf)])
SessionDep = Annotated[Session, Depends(get_session)]


def _ready(request: Request) -> None:
    status = get_system_status(request.app.state.settings, request.app.state.engine)
    if not status.schema.up_to_date:
        raise HTTPException(409, "Run careeros migrate before opening career intelligence.")


@router.get("/market-intelligence", response_class=HTMLResponse)
def market(request: Request, session: SessionDep, brief_id: str | None = None) -> HTMLResponse:
    _ready(request)
    brief = session.get(MarketBrief, brief_id) if brief_id else latest_brief(session)
    if brief_id and brief is None:
        raise HTTPException(404, "Briefing not found")
    report = MarketReport.model_validate(brief.report_json) if brief else None
    history = list(
        session.scalars(select(MarketBrief).order_by(MarketBrief.created_at.desc()).limit(20))
    )
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request,
        "market.html",
        {
            "brief": brief,
            "report": report,
            "history": history,
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/market-intelligence/refresh")
def refresh(request: Request, session: SessionDep) -> RedirectResponse:
    _ready(request)
    brief = generate_brief(session)
    session.commit()
    return RedirectResponse(f"/market-intelligence?brief_id={brief.id}", status_code=303)
