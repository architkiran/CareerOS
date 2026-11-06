from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from careeros.db.models import Evidence
from careeros.modules.companies import service
from careeros.modules.research import service as research
from careeros.modules.scheduler.worker import enqueue_rescore
from careeros.web import forms
from careeros.web.csrf import verify_csrf
from careeros.web.deps import get_session

router = APIRouter(dependencies=[Depends(verify_csrf)])
SessionDep = Annotated[Session, Depends(get_session)]


def _render(request: Request, template: str, context: dict[str, Any]) -> HTMLResponse:
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request, template, context
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/companies", response_class=HTMLResponse)
def index(request: Request, session: SessionDep) -> HTMLResponse:
    return _render(request, "companies.html", {"rows": service.list_companies(session)})


@router.post("/companies/watchlist")
def prepare_watchlist(session: SessionDep) -> RedirectResponse:
    service.ensure_watchlist(session)
    session.commit()
    return RedirectResponse("/companies", status_code=303)


@router.get("/companies/{company_id}", response_class=HTMLResponse)
def detail(company_id: str, request: Request, session: SessionDep) -> HTMLResponse:
    try:
        context = service.workspace(session, company_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _render(request, "company.html", context)


@router.post("/companies/{company_id}/research")
def open_workspace(company_id: str, session: SessionDep) -> RedirectResponse:
    try:
        service.open_company_research(session, company_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    return RedirectResponse(f"/companies/{company_id}", status_code=303)


@router.post("/companies/{company_id}/evidence")
async def add_evidence(company_id: str, request: Request, session: SessionDep) -> RedirectResponse:
    form = await request.form()
    try:
        data = research.EvidenceIn.model_validate(
            {
                "claim_type": forms.text(form, "claim_type") or "other",
                "claim_text": forms.text(form, "claim_text") or "",
                "source_kind": forms.text(form, "source_kind") or "official_company",
                "source_url": forms.text(form, "source_url") or "",
                "source_title": forms.text(form, "source_title"),
                "source_date": forms.text(form, "source_date"),
                "short_excerpt": forms.text(form, "short_excerpt"),
                "confidence": forms.text(form, "confidence") or "medium",
                "checked": forms.checkbox(form, "checked"),
            }
        )
        item = service.open_company_research(session, company_id)
        research.add_evidence(session, item.id, data)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(
            422, "Check the claim, HTTP(S) source URL, dates and evidence fields."
        ) from exc
    enqueue_rescore(session, "company evidence changed")
    session.commit()
    return RedirectResponse(f"/companies/{company_id}#evidence", status_code=303)


@router.post("/companies/{company_id}/evidence/{evidence_id}/review")
async def review(
    company_id: str, evidence_id: str, request: Request, session: SessionDep
) -> RedirectResponse:
    form = await request.form()
    decision = forms.text(form, "decision")
    if decision not in ("accepted", "rejected", "pending"):
        raise HTTPException(422, "Choose an evidence review decision.")
    evidence = session.get(Evidence, evidence_id)
    if evidence is None or evidence.company_id != company_id or evidence.job_id is not None:
        raise HTTPException(404, "Company evidence not found")
    research.review_evidence(session, evidence_id, decision)  # type: ignore[arg-type]
    enqueue_rescore(session, "company evidence reviewed")
    session.commit()
    return RedirectResponse(f"/companies/{company_id}#evidence", status_code=303)
