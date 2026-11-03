from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from careeros.modules.analytics.service import MIN_SAMPLE, compute
from careeros.web.deps import get_session

router = APIRouter()


@router.get("/analytics", response_class=HTMLResponse)
def analytics_page(
    request: Request, session: Annotated[Session, Depends(get_session)]
) -> HTMLResponse:
    data = compute(session)
    top = max((s.count for s in data.funnel), default=0) or 1
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request, "analytics.html", {"a": data, "top": top, "min_sample": MIN_SAMPLE}
    )
    return response
