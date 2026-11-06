"""Allowlisted tools for the first career review. No submit/send/profile-write tools."""

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from careeros.common.clock import utcnow
from careeros.db.models import AgentRun, Application, Approval, Job, Mission, Source
from careeros.modules.agents.contracts import (
    AgentExecutionError,
    AgentOutput,
    AgentTaskInput,
    ArtifactRef,
)
from careeros.modules.agents.registry import SUPPORTED_VERSIONS
from careeros.modules.analytics.service import compute
from careeros.modules.ingestion.service import run_all
from careeros.modules.matching.service import score_jobs
from careeros.modules.profile.service import profile_summary
from careeros.modules.research.service import open_research, research_for_job
from careeros.modules.sources.http import Fetcher


def execute(
    factory: sessionmaker[Session],
    payload: dict[str, Any],
    fetcher_factory: Callable[[], Fetcher],
    *,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    inputs = AgentTaskInput.model_validate(payload)
    run_id = inputs.agent_run_id
    with factory() as session:
        run = session.get(AgentRun, run_id)
        if run is None or run.status != "running":
            raise AgentExecutionError("Agent run is not running.")
        mission = session.get(Mission, run.mission_id)
        if mission is None or mission.version not in SUPPORTED_VERSIONS:
            raise AgentExecutionError("Unsupported workflow version; upgrade before continuing.")
        if mission.status == "cancelled":
            raise AgentExecutionError("Mission cancelled before this step started.")
        key = run.agent_key
        target = inputs.application_id if key == "application" else inputs.job_id
        if key in ("application", "interview") and mission.workflow != f"{key}:{target}":
            raise AgentExecutionError("The saved task target does not match its mission.")
    if key == "discovery":

        def cancelled() -> bool:
            with factory() as check:
                current = check.get(Mission, run.mission_id)
                return current is None or current.status == "cancelled"

        with factory() as check:
            enabled_count = int(
                check.scalar(
                    select(func.count()).select_from(Source).where(Source.enabled.is_(True))
                )
                or 0
            )
        if inputs.source_ids == []:
            results = []
        else:
            fetcher = fetcher_factory()
            try:
                results = run_all(
                    factory, fetcher, source_ids=inputs.source_ids, should_stop=cancelled
                )
            finally:
                fetcher.close()
        failed = sum(r.status == "failed" for r in results)
        if results and failed == len(results):
            raise AgentExecutionError("All configured feeds failed. Check Sources before retrying.")
        metrics = {
            "sources": len(results),
            "failed_sources": failed,
            "new_jobs": sum(r.new for r in results),
            "updated_jobs": sum(r.updated for r in results),
            "invalid_jobs": sum(r.invalid for r in results),
        }
        warnings = []
        if not results and not enabled_count:
            warnings.append("No enabled sources. Add a company feed in Sources to discover jobs.")
        if failed:
            warnings.append("Some feeds failed. Results cover only feeds checked successfully.")
        if metrics["invalid_jobs"]:
            warnings.append("Some postings could not be normalized. Inspect source run details.")
        return AgentOutput(
            summary=(
                "No feeds are due under their scheduled refresh policies."
                if inputs.source_ids == [] and enabled_count
                else f"Checked {len(results)} feeds and discovered {metrics['new_jobs']} new jobs."
            ),
            metrics=metrics,
            warnings=warnings,
        ).model_dump()
    with factory() as session:
        if key == "application":
            if inputs.application_id is None or data_dir is None:
                raise AgentExecutionError(
                    "Draft preparation needs an application and configured data directory."
                )
            output = _prepare_application(session, inputs.application_id, data_dir)
        elif key == "interview":
            from careeros.modules.interviews.contracts import Preparation
            from careeros.modules.interviews.service import prepare_plan

            if inputs.job_id is None:
                raise AgentExecutionError("Interview preparation needs a saved job.")
            plan = prepare_plan(session, inputs.job_id)
            content = Preparation.model_validate(plan.content_json)
            output = AgentOutput(
                summary=f"Prepared {len(content.questions)} role-specific practice questions.",
                metrics={
                    "questions": len(content.questions),
                    "verified_skill_overlap": len(content.verified_skill_overlap),
                },
                artifacts=[ArtifactRef(kind="interview_plan", id=plan.id)],
                warnings=content.warnings,
            )
        else:
            output = _local_step(session, key)
        session.commit()
        return output.model_dump()


def _prepare_application(session: Session, application_id: str, data_dir: Path) -> AgentOutput:
    from careeros.modules.applications import service as applications
    from careeros.modules.documents import service as documents

    app = session.get(Application, application_id)
    if app is None or app.status not in ("preparing", "ready"):
        raise AgentExecutionError("This application is no longer available for draft preparation.")
    try:
        resume = documents.generate(session, app.id, "resume", data_dir)
        letter = documents.generate(session, app.id, "cover_letter", data_dir)
        for doc in (resume, letter):
            documents.verify_integrity(doc)
    except documents.DocumentError as exc:
        raise AgentExecutionError(
            "Draft preparation failed. Review your profile and document workspace."
        ) from exc
    applications.sync_ready(session, app, resume.status == "ready")
    needs_review = sum(d.status != "ready" for d in (resume, letter))
    warnings = [
        "These Word drafts use a generic template and do not preserve your master PDF layout.",
        "Review every statement and layout before requesting approval; nothing was submitted.",
    ]
    if needs_review:
        warnings.append(
            "Document QA requires your attention. Warnings were not acknowledged automatically."
        )
    return AgentOutput(
        summary="Prepared a resume and cover-letter draft for your review.",
        metrics={"drafts": 2, "drafts_needing_review": needs_review},
        artifacts=[ArtifactRef(kind="application", id=app.id)]
        + [ArtifactRef(kind="document", id=d.id) for d in (resume, letter)],
        warnings=warnings,
    )


def _local_step(session: Session, key: str) -> AgentOutput:
    if key == "market":
        from careeros.modules.market.contracts import MarketReport
        from careeros.modules.market.service import generate_brief

        brief = generate_brief(session)
        report = MarketReport.model_validate(brief.report_json)
        return AgentOutput(
            summary=f"Found {len(report.findings)} evidence-backed role themes "
            f"across {report.recent_active_jobs} recently observed jobs.",
            metrics={
                "role_themes": len(report.findings),
                "recent_active_jobs": report.recent_active_jobs,
                "fresh_sources": len(report.fresh_source_ids),
            },
            warnings=[
                w for w in report.warnings if not w.startswith("No evidence-backed role themes")
            ],
            artifacts=[ArtifactRef(kind="market_brief", id=brief.id)],
        )
    if key == "matching":
        result = score_jobs(session, commit_every=25)
        profile = profile_summary(session)
        warnings = []
        if not profile.exists or not profile.verified or not profile.lanes_enabled:
            warnings.append(
                "Matching needs verified profile evidence and at least one enabled role lane."
            )
        return AgentOutput(
            summary=f"Reviewed {result.jobs} jobs: {result.passing} pass; "
            f"{result.needs_review} need eligibility review.",
            metrics=asdict(result),
            warnings=warnings,
        )
    if key == "research":
        from careeros.modules.companies.service import ensure_watchlist

        company_workspaces = ensure_watchlist(session)
        ids = list(
            session.scalars(
                select(Job.id).where(Job.status == "active", Job.triage_status == "shortlisted")
            )
        )
        created = 0
        for job_id in ids:
            if research_for_job(session, job_id) is None:
                open_research(session, job_id)
                created += 1
        return AgentOutput(
            summary=f"Checked {len(ids)} shortlisted jobs; opened {created} evidence reviews "
            f"and {company_workspaces} company workspaces.",
            metrics={
                "shortlisted_jobs": len(ids),
                "new_reviews": created,
                "new_company_workspaces": company_workspaces,
            },
        )
    if key == "analytics":
        analytics = compute(session)
        return AgentOutput(
            summary="Updated the career funnel. Conversion comparisons retain sample-size limits.",
            metrics={step.key: step.count for step in analytics.funnel},
        )
    if key == "verification":
        profile = profile_summary(session)
        failing = int(
            session.scalar(
                select(func.count())
                .select_from(Source)
                .where(Source.enabled.is_(True), Source.last_error.is_not(None))
            )
            or 0
        )
        approvals = int(
            session.scalar(
                select(func.count())
                .select_from(Approval)
                .where(Approval.status.in_(("pending", "approved")), Approval.expires_at > utcnow())
            )
            or 0
        )
        warnings = []
        if failing:
            warnings.append("Enabled feeds have errors. Check Sources for recovery details.")
        if profile.gaps or not profile.verified:
            warnings.append(
                "Career profile has readiness gaps. Review Profile before preparing materials."
            )
        return AgentOutput(
            summary=f"Quality check: {failing} feeds need attention; "
            f"{approvals} approvals await action.",
            metrics={
                "failing_sources": failing,
                "profile_gaps": len(profile.gaps),
                "unverified_items": profile.unverified,
                "approvals_waiting": approvals,
            },
            warnings=warnings,
        )
    raise AgentExecutionError("This agent has no permitted execution tool.")
