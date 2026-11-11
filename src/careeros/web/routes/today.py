"""Career OS 2.0 command center: verdicts, evidence and the original posting, one click away."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.modules.eligibility import service as eligibility
from careeros.modules.eligibility.engine import ROLE_FAMILIES
from careeros.web.deps import get_session

router = APIRouter()


@router.get("/today", response_class=HTMLResponse)
def today_page(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    family: str | None = None,
) -> HTMLResponse:
    families = [(key, label) for key, label, _ in ROLE_FAMILIES]
    if family not in {key for key, _ in families}:
        family = None
    now = utcnow()
    digest = eligibility.build_digest(session, family=family, now=now)
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request,
        "today.html",
        {"d": digest, "now": now, "families": families, "family": family},
    )
    response.headers["Cache-Control"] = "no-store"
    return response
