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
        {
            "d": digest,
            "now": now,
            "families": families,
            "family": family,
            "fresh_label": eligibility.FRESH_LABEL,
        },
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


SOURCE_KIND = {
    "greenhouse": "Greenhouse career sites",
    "lever": "Lever career sites",
    "ashby": "Ashby career sites",
    "smartrecruiters": "SmartRecruiters career sites",
    "workday": "Workday career sites",
    "community": "Curated new-graduate list",
    "jobicy": "Jobicy remote board",
    "remotive": "Remotive remote board",
    "wwr": "We Work Remotely",
}
LEVELS = (
    ("A", "The posting says so", "A quote from the posting itself states sponsorship."),
    ("B", "The employer has done it", "Certified filings on record. This role is unconfirmed."),
    ("C", "Hearsay", "A third-party tag, or a filer whose name only looks similar."),
    ("U", "Nothing either way", "No credible evidence. Held in the research queue."),
    ("D", "The posting rules it out", "Rejected, with the sentence that rules it out."),
)


def landing(request: Request, session: Session) -> HTMLResponse:
    """Home: what this is, the freshest cleared roles, and how a role earns its place."""
    from sqlalchemy import func, select

    from careeros.db.models import JobSourceRecord, JobVerdict, Source

    now = utcnow()
    digest = eligibility.build_digest(session, now=now)
    fresh = [c for c in digest.eligible if c.fresh != "older"][:7]
    by_level = dict(
        session.execute(
            select(JobVerdict.sponsorship_level, func.count())
            .join(Job, Job.id == JobVerdict.job_id)
            .where(
                Job.status == "active",
                # A to U count roles still on the board; D counts the ones it turned away.
                (JobVerdict.verdict != "rejected") | (JobVerdict.sponsorship_level == "D"),
            )
            .group_by(JobVerdict.sponsorship_level)
        ).all()
    )
    sources = session.execute(
        select(
            Source.source_type, func.count(func.distinct(Source.id)), func.count(JobSourceRecord.id)
        )
        .outerjoin(JobSourceRecord, JobSourceRecord.source_id == Source.id)
        .where(Source.enabled.is_(True))
        .group_by(Source.source_type)
        .order_by(func.count(JobSourceRecord.id).desc())
    ).all()
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request,
        "landing.html",
        {
            "d": digest,
            "now": now,
            "fresh": fresh,
            "example": next(iter(fresh or digest.eligible or digest.research), None),
            "levels": [(k, name, text, by_level.get(k, 0)) for k, name, text in LEVELS],
            "sources": [(SOURCE_KIND.get(kind, kind), n, jobs) for kind, n, jobs in sources],
            "evaluated": sum(
                digest.counts.get(k, 0) for k in ("eligible", "research", "review", "rejected")
            ),
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response
