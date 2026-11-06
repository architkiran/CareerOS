"""A small auditable source catalog. Candidate suggestions never silently enable a feed."""

from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.modules.events.service import record_event
from careeros.modules.sources.registry import SourceIn, find_source, list_sources
from careeros.modules.system.settings_store import get_setting, set_setting

CATALOG = (
    {
        "key": "formlabs",
        "type": "greenhouse",
        "token": "formlabs",
        "name": "Formlabs",
        "url": "https://formlabs.com/company/careers/",
        "scope": "Manufacturing and 3D-printing technology; official company hiring feed.",
    },
    {
        "key": "captech",
        "type": "smartrecruiters",
        "token": "CapTechConsulting",
        "name": "CapTech Consulting",
        "url": "https://www.captechconsulting.com/careers",
        "scope": "Consulting and technology delivery; US company hiring feed.",
    },
    {
        "key": "remotive",
        "type": "remotive",
        "token": "public",
        "name": "Remotive",
        "url": "https://remotive.com/remote-jobs/api",
        "scope": "Remote roles across employers; attribution preserved. "
        "Publication is delayed by 24 hours.",
    },
    {
        "key": "jobicy",
        "type": "jobicy",
        "token": "usa",
        "name": "Jobicy",
        "url": "https://github.com/Jobicy/remote-jobs-api",
        "scope": "US remote roles across employers; hourly provider limit enforced.",
    },
    {
        "key": "wise",
        "type": "smartrecruiters",
        "token": "wise",
        "name": "Wise",
        "url": "https://wise.jobs/early-careers",
        "scope": "US postings; payments and financial technology",
    },
    {
        "key": "databricks",
        "type": "greenhouse",
        "token": "databricks",
        "name": "Databricks",
        "url": "https://boards-api.greenhouse.io/v1/boards/databricks/jobs",
        "scope": "Data platforms and analytics; all locations, filtered by your lanes",
    },
    {
        "key": "fivetran",
        "type": "greenhouse",
        "token": "fivetran",
        "name": "Fivetran",
        "url": "https://boards-api.greenhouse.io/v1/boards/fivetran/jobs",
        "scope": "Data integration and engineering; all locations, filtered by your lanes",
    },
)
REPORT_KEY = "sources.coverage_report"


def proposals(session: Session) -> list[dict[str, str]]:
    return [dict(row) for row in CATALOG if find_source(session, row["type"], row["token"]) is None]


def audit(session: Session) -> dict[str, object]:
    sources = list_sources(session)
    preferences = get_setting(session, "career.preferences", {})
    targets = preferences.get("target_companies", []) if isinstance(preferences, dict) else []
    names = {s.display_name.casefold() for s in sources if s.enabled}
    gaps = (
        [name for name in targets[:50] if isinstance(name, str) and name.casefold() not in names]
        if isinstance(targets, list)
        else []
    )
    report: dict[str, object] = {
        "generated_at": utcnow().isoformat(),
        "enabled_sources": sum(s.enabled for s in sources),
        "failing_sources": sum(s.enabled and bool(s.last_error) for s in sources),
        "candidate_feeds": len(proposals(session)),
        "uncovered_targets": gaps,
        "scope": "Configured feeds and a reviewed public API catalog; "
        "not an exhaustive web search.",
    }
    set_setting(session, REPORT_KEY, report)
    record_event(
        session,
        "sources.audit_completed",
        "Source coverage reviewed; candidate feeds are ready for inspection.",
        metadata={"candidate_feeds": report["candidate_feeds"], "uncovered_targets": len(gaps)},
    )
    return report


def proposal_input(key: str) -> SourceIn:
    row = next((row for row in CATALOG if row["key"] == key), None)
    if row is None:
        raise LookupError("Source proposal not found")
    return SourceIn.model_validate({k: row[k] for k in ("type", "token", "name")})
