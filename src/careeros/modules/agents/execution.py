"""Allowlisted tools for the first career review. No submit/send/profile-write tools."""

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from careeros.common.clock import utcnow
from careeros.db.models import AgentRun, Approval, Job, Mission, Source
from careeros.modules.agents.contracts import AgentExecutionError, AgentOutput, AgentTaskInput
from careeros.modules.agents.registry import SUPPORTED_VERSIONS
from careeros.modules.analytics.service import compute
from careeros.modules.ingestion.service import run_all
from careeros.modules.matching.service import score_jobs
from careeros.modules.profile.service import profile_summary
from careeros.modules.research.service import open_research, research_for_job
from careeros.modules.sources.http import Fetcher


def execute(
    factory: sessionmaker[Session], payload: dict[str, Any], fetcher_factory: Callable[[], Fetcher]
) -> dict[str, Any]:
    run_id = AgentTaskInput.model_validate(payload).agent_run_id
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
    if key == "discovery":
        fetcher = fetcher_factory()
        try:
            results = run_all(factory, fetcher)
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
        if not results:
            warnings.append("No enabled sources. Add a company feed in Sources to discover jobs.")
        if failed:
            warnings.append("Some feeds failed. Results cover only feeds checked successfully.")
        if metrics["invalid_jobs"]:
            warnings.append("Some postings could not be normalized. Inspect source run details.")
        return AgentOutput(
            summary=f"Checked {len(results)} feeds and discovered {metrics['new_jobs']} new jobs.",
            metrics=metrics,
            warnings=warnings,
        ).model_dump()
    with factory() as session:
        output = _local_step(session, key)
        session.commit()
        return output.model_dump()


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
            summary=f"Checked {len(ids)} shortlisted jobs; opened {created} evidence reviews.",
            metrics={"shortlisted_jobs": len(ids), "new_reviews": created},
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
