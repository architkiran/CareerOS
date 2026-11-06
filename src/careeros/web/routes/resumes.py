from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from careeros.modules.resumes import service
from careeros.web.deps import get_session

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/resumes", response_class=HTMLResponse)
def references(request: Request, session: SessionDep) -> HTMLResponse:
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request,
        "resumes.html",
        {"references": service.list_references(session), "labels": service.LABELS},
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/resumes/{reference_id}/download")
def download(reference_id: str, request: Request, session: SessionDep) -> FileResponse:
    try:
        reference = service.get_reference(session, reference_id)
        path = service.checked_path(request.app.state.settings.data_dir, reference)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except service.ReferenceError as exc:
        raise HTTPException(409, str(exc)) from exc
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"{reference.family}-reference.pdf",
        headers={"Cache-Control": "no-store"},
    )
