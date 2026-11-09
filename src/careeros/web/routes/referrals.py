from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from careeros.db.models import Company, Job, OutreachContact, ReferralPath
from careeros.modules.jobs.service import JobFilters, JobRow, get_job_detail, list_jobs
from careeros.modules.matching.service import best_matches
from careeros.modules.outreach import service as outreach
from careeros.modules.referrals import service
from careeros.web import forms
from careeros.web.csrf import verify_csrf
from careeros.web.deps import error_messages, get_session

router = APIRouter(dependencies=[Depends(verify_csrf)])
SessionDep = Annotated[Session, Depends(get_session)]


def _context(session: Session, job_id: str | None, q: str | None = None) -> dict[str, Any]:
    rows, _ = list_jobs(session, JobFilters(recommended=True, sort="published", q=q))
    saved, _ = list_jobs(session, JobFilters(triage="saved", eligibility="any", q=q, status="all"))
    shortlisted, _ = list_jobs(
        session, JobFilters(triage="shortlisted", eligibility="any", q=q, status="all")
    )
    tracked_query = (
        select(Job, Company.canonical_name, func.max(ReferralPath.updated_at).label("updated"))
        .join(Company, Company.id == Job.company_id)
        .join(ReferralPath, ReferralPath.job_id == Job.id)
        .group_by(Job.id, Company.canonical_name)
        .order_by(func.max(ReferralPath.updated_at).desc())
        .limit(20)
    )
    if q:
        tracked_query = tracked_query.where(
            or_(Job.title.ilike(f"%{q}%"), Company.canonical_name.ilike(f"%{q}%"))
        )
    tracked = [JobRow(job, company, []) for job, company, _ in session.execute(tracked_query)]
    # Tracking a connection keeps the role available even after closure or rescoring.
    targets = list({row.job.id: row for row in [*tracked, *saved, *shortlisted, *rows]}.values())[
        :20
    ]
    detail = (
        get_job_detail(session, job_id)
        if job_id
        else get_job_detail(session, targets[0].job.id)
        if targets
        else None
    )
    if job_id and detail is None:
        raise HTTPException(404, "Role not found")
    selected_match = best_matches(session, [detail.job.id]).get(detail.job.id) if detail else None
    return {
        "selected_match": selected_match,
        "targets": targets,
        "q": q or "",
        "detail": detail,
        "contacts": service.contacts_for(session, detail.company.id) if detail else [],
        "paths": service.paths_for(session, detail.job.id) if detail else [],
        "links": service.search_links(detail.company.canonical_name, detail.job.title)
        if detail
        else [],
        "relationships": service.RELATIONSHIPS,
        "statuses": service.STATUSES,
        "overview": service.overview(session),
    }


def _render(request: Request, context: dict[str, Any], status: int = 200) -> HTMLResponse:
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request, "referrals.html", context, status_code=status
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/referrals", response_class=HTMLResponse)
def page(
    request: Request, session: SessionDep, job_id: str | None = None, q: str | None = None
) -> HTMLResponse:
    return _render(request, _context(session, job_id, (q or "").strip()[:200] or None))


@router.post("/referrals/{job_id}/paths", response_model=None)
async def add_path(
    job_id: str, request: Request, session: SessionDep
) -> HTMLResponse | RedirectResponse:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Role not found")
    f = await request.form()
    try:
        data = service.PathIn(
            relationship=forms.text(f, "relationship") or "research",
            via=forms.text(f, "via"),
            notes=forms.text(f, "notes"),
        )
        contact_id = forms.text(f, "contact_id")
        if not contact_id:
            contact_data = outreach.ContactIn(
                name=forms.text(f, "name") or "",
                role=forms.text(f, "role"),
                public_profile_url=forms.text(f, "public_profile_url"),
                source_url=forms.text(f, "source_url"),
            )
            # Repeated form submissions reuse the same company-scoped saved person.
            existing = session.scalar(
                select(OutreachContact).where(
                    OutreachContact.company_id == job.company_id,
                    OutreachContact.name == contact_data.name,
                    OutreachContact.public_profile_url == contact_data.public_profile_url,
                )
            )
            contact_id = (
                existing or outreach.add_contact(session, job.company_id, contact_data)
            ).id
        service.save_path(session, job_id, contact_id, data)
        session.commit()
    except (ValidationError, ValueError, LookupError) as exc:
        session.rollback()
        errors = error_messages(exc) if isinstance(exc, ValidationError) else [str(exc)]
        return _render(request, _context(session, job_id) | {"errors": errors}, 422)
    return RedirectResponse(f"/referrals?job_id={job_id}&saved=1#paths", 303)


@router.post("/referrals/paths/{path_id}/status")
async def status(path_id: str, request: Request, session: SessionDep) -> RedirectResponse:
    f = await request.form()
    try:
        path = service.set_status(session, path_id, forms.text(f, "status") or "")
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    session.commit()
    return RedirectResponse(f"/referrals?job_id={path.job_id}#paths", 303)


@router.post("/referrals/paths/{path_id}/draft", response_model=None)
async def draft(
    path_id: str, request: Request, session: SessionDep
) -> HTMLResponse | RedirectResponse:
    path = session.get(ReferralPath, path_id)
    if path is None:
        raise HTTPException(404, "Referral path not found")
    contact = session.get(OutreachContact, path.contact_id)
    assert contact
    f = await request.form()
    try:
        text = service.request_text(session, path)
        proposal = outreach.DraftIn(
            channel="linkedin",
            recipient=contact.public_profile_url or contact.name,
            subject=text.subject,
            body=(forms.text(f, "body") or "") if "body" in f else text.body,
        )
        saved = outreach.save_draft(
            session,
            contact.id,
            proposal,
            request.app.state.settings.data_dir,
            draft_id=path.draft_id,
        )
        path.draft_id = saved.id
        session.commit()
    except (ValidationError, ValueError, LookupError) as exc:
        job_id = path.job_id
        session.rollback()
        errors = error_messages(exc) if isinstance(exc, ValidationError) else [str(exc)]
        return _render(request, _context(session, job_id) | {"errors": errors}, 422)
    return RedirectResponse(f"/referrals?job_id={path.job_id}#paths", 303)
