from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from careeros.modules.sources import registry
from careeros.web import forms
from careeros.web.csrf import verify_csrf
from careeros.web.deps import error_messages, get_session

router = APIRouter(dependencies=[Depends(verify_csrf)])
SessionDep = Annotated[Session, Depends(get_session)]


def _ctx(session: Session) -> dict[str, Any]:
    rows = [(s, registry.last_run(session, s.id)) for s in registry.list_sources(session)]
    return {"rows": rows}


def _render(request: Request, ctx: dict[str, Any], status_code: int = 200) -> HTMLResponse:
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request, "sources.html", ctx, status_code=status_code
    )
    return response


@router.get("/sources", response_class=HTMLResponse)
def sources_page(
    request: Request, session: Annotated[Session, Depends(get_session)], saved: str | None = None
) -> HTMLResponse:
    return _render(request, _ctx(session) | {"saved": saved})


@router.post("/sources")
async def add_source(request: Request, session: SessionDep) -> Response:
    f = await request.form()
    try:
        data = registry.SourceIn(
            type=forms.text(f, "type"),
            token=forms.text(f, "token") or "",
            name=forms.text(f, "name") or "",
            rate_limit_seconds=forms.text(f, "rate_limit_seconds") or 2.0,
        )
        registry.add_source(session, data)
    except ValidationError as exc:
        session.rollback()
        return _render(request, _ctx(session) | {"errors": error_messages(exc)}, 422)
    except registry.DuplicateSourceError as exc:
        session.rollback()
        return _render(request, _ctx(session) | {"errors": [str(exc)]}, 422)
    session.commit()
    return RedirectResponse("/sources?saved=1", status_code=303)


@router.post("/sources/{source_id}/toggle")
async def toggle_source(source_id: str, request: Request, session: SessionDep) -> Response:
    f = await request.form()
    try:
        registry.set_source_enabled(session, source_id, forms.checkbox(f, "enabled"))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    return RedirectResponse("/sources", status_code=303)
