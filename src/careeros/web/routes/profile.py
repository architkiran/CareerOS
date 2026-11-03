import json
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from careeros.modules.profile import service
from careeros.modules.profile.schemas import (
    ExperienceIn,
    FactIn,
    LaneIn,
    LaneRules,
    LaneWeights,
    ProfileExport,
    ProfileIn,
    ProjectIn,
    SkillIn,
    WorkAuthorizationIn,
)
from careeros.web import forms
from careeros.web.csrf import verify_csrf
from careeros.web.deps import error_messages, get_session

router = APIRouter(dependencies=[Depends(verify_csrf)])
SessionDep = Annotated[Session, Depends(get_session)]
MAX_IMPORT_BYTES = 2_000_000
KINDS = {"facts", "skills", "experience", "projects"}


def _kind(kind: str) -> service.ItemKind:
    if kind not in KINDS:
        raise HTTPException(404)
    return cast(service.ItemKind, kind)


def _render(
    request: Request, template: str, ctx: dict[str, Any], status_code: int = 200
) -> HTMLResponse:
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request, template, ctx, status_code=status_code
    )
    return response


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _profile_ctx(session: Session) -> dict[str, Any]:
    profile = service.get_profile(session)
    if profile is None:
        return {
            "profile": None,
            "basics": ProfileIn(),
            "facts": [],
            "skills": [],
            "experience": [],
            "projects": [],
            "summary": service.profile_summary(session),
        }
    return {
        "profile": profile,
        "basics": service.profile_to_input(profile),
        "facts": service.list_facts(session, profile.id),
        "skills": service.list_skills(session, profile.id),
        "experience": service.list_experience(session, profile.id),
        "projects": service.list_projects(session, profile.id),
        "summary": service.profile_summary(session),
    }


def _profile_error(request: Request, session: Session, errors: list[str]) -> HTMLResponse:
    session.rollback()
    ctx = _profile_ctx(session) | {"errors": errors}
    return _render(request, "profile.html", ctx, status_code=422)


@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, session: SessionDep, saved: str | None = None) -> HTMLResponse:
    return _render(request, "profile.html", _profile_ctx(session) | {"saved": saved})


@router.post("/profile")
async def save_basics(request: Request, session: SessionDep) -> Response:
    f = await request.form()
    try:
        data = ProfileIn(
            display_name=forms.text(f, "display_name") or "",
            email=forms.text(f, "email"),
            phone=forms.text(f, "phone"),
            current_location=forms.text(f, "current_location"),
            open_to_relocation=forms.tri_state(f, "open_to_relocation"),
            relocation_locations=forms.csv_list(f, "relocation_locations"),
            graduation_date=forms.text(f, "graduation_date"),
            availability_date=forms.text(f, "availability_date"),
            salary_floor=forms.text(f, "salary_floor"),
        )
    except ValidationError as exc:
        return _profile_error(request, session, error_messages(exc))
    service.update_profile(session, data)
    session.commit()
    return _redirect("/profile?saved=basics")


@router.post("/profile/facts")
async def add_fact(request: Request, session: SessionDep) -> Response:
    f = await request.form()
    try:
        data = FactIn(
            category=forms.text(f, "category"),
            fact_key=forms.text(f, "fact_key") or "",
            fact_value=forms.text(f, "fact_value") or "",
            source_note=forms.text(f, "source_note"),
            verified_status="verified" if forms.checkbox(f, "verified") else "unverified",
        )
    except ValidationError as exc:
        return _profile_error(request, session, error_messages(exc))
    service.add_fact(session, data)
    session.commit()
    return _redirect("/profile?saved=facts#facts")


@router.post("/profile/skills")
async def add_skill(request: Request, session: SessionDep) -> Response:
    f = await request.form()
    try:
        data = SkillIn(
            name=forms.text(f, "name") or "",
            proficiency=forms.text(f, "proficiency"),
            last_used_year=forms.text(f, "last_used_year"),
            verified_status="verified" if forms.checkbox(f, "verified") else "unverified",
        )
        service.add_skill(session, data)
    except ValidationError as exc:
        return _profile_error(request, session, error_messages(exc))
    except service.ConflictError as exc:
        return _profile_error(request, session, [str(exc)])
    session.commit()
    return _redirect("/profile?saved=skills#skills")


@router.post("/profile/experience")
async def add_experience(request: Request, session: SessionDep) -> Response:
    f = await request.form()
    try:
        data = ExperienceIn(
            organization=forms.text(f, "organization") or "",
            title=forms.text(f, "title") or "",
            start_date=forms.text(f, "start_date"),
            end_date=forms.text(f, "end_date"),
            description=forms.text(f, "description"),
            verified_status="verified" if forms.checkbox(f, "verified") else "unverified",
        )
    except ValidationError as exc:
        return _profile_error(request, session, error_messages(exc))
    service.add_experience(session, data)
    session.commit()
    return _redirect("/profile?saved=experience#experience")


@router.post("/profile/projects")
async def add_project(request: Request, session: SessionDep) -> Response:
    f = await request.form()
    try:
        data = ProjectIn(
            name=forms.text(f, "name") or "",
            description=forms.text(f, "description"),
            technologies=forms.csv_list(f, "technologies"),
            outcomes=forms.lines(f, "outcomes"),
            evidence_notes=forms.text(f, "evidence_notes"),
            verified_status="verified" if forms.checkbox(f, "verified") else "unverified",
        )
    except ValidationError as exc:
        return _profile_error(request, session, error_messages(exc))
    service.add_project(session, data)
    session.commit()
    return _redirect("/profile?saved=projects#projects")


@router.post("/profile/{kind}/{item_id}/verify")
async def verify_item(kind: str, item_id: str, request: Request, session: SessionDep) -> Response:
    item_kind = _kind(kind)
    f = await request.form()
    try:
        service.set_verified(session, item_kind, item_id, forms.text(f, "status") == "verified")
    except service.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    return _redirect(f"/profile#{kind}")


@router.post("/profile/{kind}/{item_id}/delete")
def delete_item(kind: str, item_id: str, session: SessionDep) -> Response:
    item_kind = _kind(kind)
    try:
        service.delete_item(session, item_kind, item_id)
    except service.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    return _redirect(f"/profile#{kind}")


# ---------- work authorization ----------


@router.get("/profile/work-authorization", response_class=HTMLResponse)
def work_auth_page(request: Request, session: SessionDep, saved: str | None = None) -> HTMLResponse:
    profile = service.get_profile(session)
    wa = service.get_work_authorization(session, profile.id) if profile else None
    data = service.work_authorization_to_input(wa) if wa else WorkAuthorizationIn()
    return _render(
        request,
        "work_authorization.html",
        {"wa": data, "verified_at": wa.verified_at if wa else None, "saved": saved},
    )


@router.post("/profile/work-authorization")
async def save_work_auth(request: Request, session: SessionDep) -> Response:
    f = await request.form()
    try:
        data = WorkAuthorizationIn(
            status_text=forms.text(f, "status_text"),
            requires_sponsorship_now=forms.text(f, "requires_sponsorship_now") or "unknown",
            requires_sponsorship_future=forms.text(f, "requires_sponsorship_future") or "unknown",
            authorized_until=forms.text(f, "authorized_until"),
            constraints=forms.text(f, "constraints"),
            notes=forms.text(f, "notes"),
            confirmed=forms.checkbox(f, "confirmed"),
        )
    except ValidationError as exc:
        return _render(
            request,
            "work_authorization.html",
            {"wa": WorkAuthorizationIn(), "verified_at": None, "errors": error_messages(exc)},
            status_code=422,
        )
    service.save_work_authorization(session, data)
    session.commit()
    return _redirect("/profile/work-authorization?saved=1")


# ---------- role lanes ----------


def _lanes_ctx(session: Session) -> dict[str, Any]:
    lanes = service.list_lanes(session)
    return {
        "lanes": [(lane, service.lane_rules(lane), service.lane_weights(lane)) for lane in lanes],
        "new_rules": LaneRules(),
        "new_weights": LaneWeights(),
    }


def _lane_from_form(f: Any) -> LaneIn:
    return LaneIn(
        name=forms.text(f, "name") or "",
        enabled=forms.checkbox(f, "enabled"),
        rules=LaneRules(
            title_keywords=forms.csv_list(f, "title_keywords"),
            title_exclude=forms.csv_list(f, "title_exclude"),
            required_skills=forms.csv_list(f, "required_skills"),
            preferred_skills=forms.csv_list(f, "preferred_skills"),
            seniority_allowed=forms.multi(f, "seniority_allowed"),
            employment_types=forms.multi(f, "employment_types") or ["full_time"],
            excluded_terms=forms.csv_list(f, "excluded_terms"),
            preferred_locations=forms.csv_list(f, "preferred_locations"),
            remote_ok=forms.checkbox(f, "remote_ok"),
            preferred_companies=forms.csv_list(f, "preferred_companies"),
        ),
        weights=LaneWeights(**{k: forms.text(f, f"w_{k}") or 0 for k in LaneWeights.model_fields}),
    )


def _lanes_error(request: Request, session: Session, errors: list[str]) -> HTMLResponse:
    session.rollback()
    return _render(request, "lanes.html", _lanes_ctx(session) | {"errors": errors}, status_code=422)


@router.get("/lanes", response_class=HTMLResponse)
def lanes_page(request: Request, session: SessionDep, saved: str | None = None) -> HTMLResponse:
    return _render(request, "lanes.html", _lanes_ctx(session) | {"saved": saved})


@router.post("/lanes/defaults")
def add_defaults(session: SessionDep) -> Response:
    added = service.add_default_lanes(session)
    session.commit()
    return _redirect(f"/lanes?saved=defaults-{added}")


@router.post("/lanes")
async def create_lane(request: Request, session: SessionDep) -> Response:
    f = await request.form()
    try:
        service.create_lane(session, _lane_from_form(f))
    except ValidationError as exc:
        return _lanes_error(request, session, error_messages(exc))
    except service.ConflictError as exc:
        return _lanes_error(request, session, [str(exc)])
    session.commit()
    return _redirect("/lanes?saved=created")


@router.post("/lanes/{lane_id}")
async def update_lane(lane_id: str, request: Request, session: SessionDep) -> Response:
    f = await request.form()
    try:
        service.update_lane(session, lane_id, _lane_from_form(f))
    except ValidationError as exc:
        return _lanes_error(request, session, error_messages(exc))
    except service.ConflictError as exc:
        return _lanes_error(request, session, [str(exc)])
    except service.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    return _redirect(f"/lanes?saved=updated#lane-{lane_id}")


@router.post("/lanes/{lane_id}/toggle")
async def toggle_lane(lane_id: str, request: Request, session: SessionDep) -> Response:
    f = await request.form()
    try:
        service.set_lane_enabled(session, lane_id, forms.checkbox(f, "enabled"))
    except service.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    return _redirect(f"/lanes#lane-{lane_id}")


# ---------- export / import ----------


@router.get("/profile/export.json")
def export_json(session: SessionDep, include_work_authorization: bool = False) -> Response:
    try:
        data = service.export_profile(
            session, include_work_authorization=include_work_authorization
        )
    except service.NotFoundError as exc:
        raise HTTPException(404, "No profile to export yet.") from exc
    return Response(
        data.model_dump_json(indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="careeros-profile.json"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/profile/import")
async def import_json(request: Request, session: SessionDep) -> Response:
    f = await request.form()
    upload = f.get("file")
    if upload is None or isinstance(upload, str):
        return _profile_error(request, session, ["Choose a JSON file to import."])
    raw = await upload.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        return _profile_error(request, session, ["File is too large (limit 2 MB)."])
    try:
        payload = json.loads(raw)
        data = ProfileExport.model_validate(payload)
        service.import_profile(session, data, replace=forms.checkbox(f, "replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _profile_error(request, session, ["File is not valid JSON."])
    except ValidationError as exc:
        return _profile_error(request, session, error_messages(exc)[:10])
    except service.ConflictError as exc:
        return _profile_error(request, session, [str(exc)])
    session.commit()
    return _redirect("/profile?saved=import")
