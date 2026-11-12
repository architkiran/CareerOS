from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from careeros.modules.backup.service import latest_backup
from careeros.web.csrf import verify_csrf
from careeros.web.deps import get_session

router = APIRouter(dependencies=[Depends(verify_csrf)])
SessionDep = Annotated[Session, Depends(get_session)]
SUMMARY_PROMPT_VERSION = "job-summary-v1"


def _render(
    request: Request, template: str, ctx: dict[str, Any], status_code: int = 200
) -> HTMLResponse:
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request, template, ctx, status_code=status_code
    )
    return response


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, session: SessionDep) -> HTMLResponse:
    settings = request.app.state.settings
    last = latest_backup(Path(settings.backup_dir))
    from careeros.modules.jobs.inbox import refresh_overview

    return _render(
        request,
        "settings.html",
        {
            "discovery": refresh_overview(session),
            "s": settings,
            "last_backup": last,
        },
    )
