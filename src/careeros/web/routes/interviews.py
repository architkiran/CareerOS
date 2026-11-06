from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from careeros.db.models import Application, Company, InterviewAnswer, InterviewPlan, Job
from careeros.modules.agents.service import start_interview_mission
from careeros.modules.interviews import service
from careeros.modules.interviews.contracts import AnswerIn, Preparation
from careeros.modules.system.status import get_system_status
from careeros.web import forms
from careeros.web.csrf import verify_csrf
from careeros.web.deps import get_session

router = APIRouter(dependencies=[Depends(verify_csrf)])
SessionDep = Annotated[Session, Depends(get_session)]


def _ready(request: Request) -> None:
    if not get_system_status(
        request.app.state.settings, request.app.state.engine
    ).schema.up_to_date:
        raise HTTPException(409, "Run careeros migrate before opening interview practice.")


def _render(request: Request, template: str, context: dict[str, Any]) -> HTMLResponse:
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request, template, context
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/interviews", response_class=HTMLResponse)
def index(request: Request, session: SessionDep) -> HTMLResponse:
    _ready(request)
    plans = list(
        session.scalars(select(InterviewPlan).order_by(InterviewPlan.created_at.desc()).limit(30))
    )
    jobs = session.execute(
        select(Job, Company.canonical_name)
        .join(Company)
        .outerjoin(Application)
        .where(
            Job.status == "active",
            or_(Job.triage_status == "shortlisted", Application.id.is_not(None)),
        )
        .order_by(Job.first_seen_at.desc())
        .limit(20)
    ).all()
    return _render(
        request,
        "interviews.html",
        {"plans": [(p, Preparation.model_validate(p.content_json)) for p in plans], "jobs": jobs},
    )


@router.post("/interviews/prepare/{job_id}")
def prepare(job_id: str, request: Request, session: SessionDep) -> RedirectResponse:
    _ready(request)
    try:
        mission, _ = start_interview_mission(session, job_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    return RedirectResponse(f"/missions/{mission.id}", status_code=303)


@router.get("/interviews/{plan_id}", response_class=HTMLResponse)
def detail(plan_id: str, request: Request, session: SessionDep) -> HTMLResponse:
    _ready(request)
    plan = session.get(InterviewPlan, plan_id)
    if plan is None:
        raise HTTPException(404, "Interview plan not found")
    preparation = Preparation.model_validate(plan.content_json)
    answers = {
        answer.question_id: answer
        for answer in session.scalars(
            select(InterviewAnswer).where(InterviewAnswer.plan_id == plan.id)
        )
    }
    return _render(
        request,
        "interview.html",
        {"plan": plan, "prep": preparation, "answers": answers, "answered": len(answers)},
    )


@router.post("/interviews/{plan_id}/answers/{question_id}")
async def answer(
    plan_id: str, question_id: str, request: Request, session: SessionDep
) -> RedirectResponse:
    _ready(request)
    form = await request.form()
    try:
        data = AnswerIn(
            answer=forms.text(form, "answer") or "",
            confidence=forms.text(form, "confidence"),
            reflection=forms.text(form, "reflection"),
        )
        service.save_answer(session, plan_id, question_id, data)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValidationError, service.InterviewError) as exc:
        raise HTTPException(
            422,
            "Enter a nonempty answer up to 20,000 characters, confidence from 0 "
            "to 3, and a valid question.",
        ) from exc
    session.commit()
    return RedirectResponse(f"/interviews/{plan_id}#question-{question_id}", status_code=303)


@router.post("/interviews/{plan_id}/feedback")
async def feedback(plan_id: str, request: Request, session: SessionDep) -> RedirectResponse:
    _ready(request)
    form = await request.form()
    try:
        service.save_feedback(session, plan_id, forms.text(form, "feedback") or "")
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except service.InterviewError as exc:
        raise HTTPException(422, str(exc)) from exc
    session.commit()
    return RedirectResponse(f"/interviews/{plan_id}#feedback", status_code=303)


@router.post("/interviews/{plan_id}/complete")
async def complete(plan_id: str, request: Request, session: SessionDep) -> RedirectResponse:
    _ready(request)
    form = await request.form()
    try:
        service.complete_plan(session, plan_id, confirmed=forms.checkbox(form, "confirmed"))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except service.InterviewError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return RedirectResponse(f"/interviews/{plan_id}", status_code=303)
