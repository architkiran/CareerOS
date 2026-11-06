from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from careeros.modules.ingestion.manual import JobImport, import_job
from careeros.modules.scheduler.worker import enqueue_rescore
from careeros.web import forms
from careeros.web.csrf import verify_csrf
from careeros.web.deps import get_session

router = APIRouter(dependencies=[Depends(verify_csrf)])
SessionDep = Annotated[Session, Depends(get_session)]


def render(request: Request, error: str | None = None, status: int = 200) -> HTMLResponse:
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request, "job_import.html", {"error": error}, status_code=status
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/opportunities/import")
def page(request: Request) -> HTMLResponse:
    return render(request)


@router.post("/opportunities/import")
async def save(request: Request, session: SessionDep) -> Response:
    form = await request.form()
    try:
        data = JobImport(
            title=forms.text(form, "title") or "",
            company=forms.text(form, "company") or "",
            url=forms.text(form, "url") or "",
            description=forms.text(form, "description") or "",
            location=forms.text(form, "location") or "",
            confirmed=forms.checkbox(form, "confirmed"),
        )
        job_id = import_job(session, data)
    except (ValidationError, ValueError):
        session.rollback()
        return render(
            request,
            "Enter a role, employer, valid job URL and at least 30 characters of posting text. "
            "Confirm the source before saving.",
            422,
        )
    enqueue_rescore(session, "user supplied a job")
    session.commit()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)
