"""Career OS 2.0 command center: verdicts, evidence and the original posting, one click away."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import Company, Job
from careeros.modules.eligibility import service as eligibility
from careeros.modules.eligibility.engine import ROLE_FAMILIES
from careeros.modules.sponsorship import lca
from careeros.web.csrf import verify_csrf
from careeros.web.deps import get_session

router = APIRouter(dependencies=[Depends(verify_csrf)])


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


@router.post("/today/jobs/{job_id}/confirm-employer")
async def confirm_employer(
    job_id: str, request: Request, session: Annotated[Session, Depends(get_session)]
) -> Response:
    """The candidate confirms which LCA filer names are this employer's legal entity."""
    job = session.get(Job, job_id)
    company = session.get(Company, job.company_id) if job is not None else None
    if job is None or company is None:
        raise HTTPException(404, "Job not found")
    form = await request.form()
    filers = [v for v in form.getlist("filer") if isinstance(v, str) and v][:12]
    try:
        lca.confirm_alias(session, company.canonical_name, filers)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(422, str(exc)) from exc
    eligibility.evaluate_all(session, company_id=company.id)
    session.commit()
    return RedirectResponse("/today", status_code=303)
