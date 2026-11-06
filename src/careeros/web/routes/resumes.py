from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from careeros.db.models import Application, Company, Document, Job
from careeros.modules.documents.latex import compiler_path
from careeros.modules.resumes import service
from careeros.web.deps import get_session

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/resumes", response_class=HTMLResponse)
def references(request: Request, session: SessionDep) -> HTMLResponse:
    application_rows = session.execute(
        select(Application, Job, Company.canonical_name)
        .select_from(Application)
        .join(Job, Job.id == Application.job_id)
        .join(Company, Company.id == Job.company_id)
        .order_by(Application.updated_at.desc())
    ).all()
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request,
        "resumes.html",
        {
            "references": service.list_references(session),
            "labels": service.LABELS,
            "compiler_ready": compiler_path() is not None,
            "labels_by_app": {
                a.id: f"{job.title} · {company}" for a, job, company in application_rows
            },
            "applications": application_rows,
            "drafts": list(
                session.scalars(
                    select(Document)
                    .where(Document.document_type == "resume")
                    .order_by(Document.generated_at.desc())
                    .limit(30)
                )
            ),
        },
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
        filename="Archit_Kiran_Kumar_Resume.pdf",
        headers={"Cache-Control": "no-store"},
    )
