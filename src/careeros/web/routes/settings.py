from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from careeros.db.models import Company, Job
from careeros.modules.backup.service import latest_backup
from careeros.modules.models.gateway import (
    JobSummary,
    ModelGateway,
    ModelOutputError,
    ModelUnavailable,
    OllamaProvider,
    usage_summary,
)
from careeros.web.csrf import verify_csrf
from careeros.web.deps import get_session

router = APIRouter(dependencies=[Depends(verify_csrf)])
SessionDep = Annotated[Session, Depends(get_session)]
SUMMARY_PROMPT_VERSION = "job-summary-v1"


def _render(
    request: Request, template: str, ctx: dict[str, Any], status_code: int = 200
) -> HTMLResponse:
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request, template, ctx, status_code=status_code
    )
    return response


def _gateway(request: Request) -> ModelGateway:
    gw = getattr(request.app.state, "model_gateway", None)
    return gw if gw is not None else ModelGateway(request.app.state.settings)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, session: SessionDep) -> HTMLResponse:
    settings = request.app.state.settings
    last = latest_backup(Path(settings.backup_dir))
    from careeros.modules.jobs.inbox import refresh_overview

    return _render(
        request,
        "settings.html",
        {
            "discovery": refresh_overview(session),
            "s": settings,
            "usage": usage_summary(session),
            "gateway_enabled": _gateway(request).enabled,
            "last_backup": last,
        },
    )


@router.post("/settings/model/test", response_class=HTMLResponse)
def test_model(request: Request, session: SessionDep) -> HTMLResponse:
    settings = request.app.state.settings
    ctx: dict[str, Any] = {
        "s": settings,
        "usage": usage_summary(session),
        "gateway_enabled": _gateway(request).enabled,
        "last_backup": latest_backup(Path(settings.backup_dir)),
    }
    if settings.model_provider != "ollama":
        ctx["test_result"] = (
            "warn",
            "No model is configured. That's fine: everything works without one.",
        )
    else:
        try:
            models = OllamaProvider(settings.ollama_base_url, settings.ollama_model).ping()
            ok = settings.ollama_model in models
            ctx["test_result"] = (
                "ok" if ok else "warn",
                f"Ollama is running. Installed models: {', '.join(models) or 'none'}."
                + ("" if ok else f" '{settings.ollama_model}' isn't installed."),
            )
        except ModelUnavailable as exc:
            ctx["test_result"] = ("error", str(exc))
    return _render(request, "settings.html", ctx)


@router.post("/jobs/{job_id}/summary", response_class=HTMLResponse)
def summarize(job_id: str, request: Request, session: SessionDep) -> HTMLResponse:
    from careeros.web.routes.jobs import job_detail_response

    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    company = session.get(Company, job.company_id)
    try:
        result = _gateway(request).run(
            session,
            task="job_summary",
            prompt_version=SUMMARY_PROMPT_VERSION,
            instructions=f"Summarise the {job.title} role at "
            f"{company.canonical_name if company else 'this company'} in 2-3 sentences "
            "and list up to 8 key requirements exactly as stated.",
            untrusted_text=job.description_text,
            schema=JobSummary,
        )
    except (ModelUnavailable, ModelOutputError) as exc:
        session.commit()  # keep the usage log entry
        return job_detail_response(request, session, job_id, {"summary_error": str(exc)})
    session.commit()
    return job_detail_response(
        request, session, job_id, {"ai_summary": result.value, "ai_meta": result}
    )
