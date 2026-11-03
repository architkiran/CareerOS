from dataclasses import replace
from typing import Any

from careeros.db.models import RoleLane
from careeros.modules.matching.inputs import JobInput, LaneInput, MatchInput, ProfileInput
from careeros.modules.matching.service import build_lane_input
from careeros.modules.profile.defaults import DEFAULT_LANES


def job(**kw: Any) -> JobInput:
    base = dict(
        title="Data Analyst",
        company="ExamplePay",
        location_text="Boston, MA",
        workplace_type=None,
        employment_type="full_time",
        description="We use SQL and Python with Tableau dashboards.",
        salary_min=None,
        salary_max=None,
        salary_interval=None,
        status="active",
    )
    return JobInput(**(base | kw))  # type: ignore[arg-type]


def lane(**kw: Any) -> LaneInput:
    d = DEFAULT_LANES[0]
    row = RoleLane(
        name=d.name,
        enabled=True,
        rules_json=d.rules.model_dump(),
        scoring_weights_json=d.weights.model_dump(),
    )
    return replace(build_lane_input(row), **kw)


def profile(**kw: Any) -> ProfileInput:
    base = dict(
        verified_skills=("SQL", "Python"),
        evidence_text="built sql and python pipelines",
        has_verified_evidence=True,
        current_location="Boston, MA",
        open_to_relocation=True,
        relocation_locations=("NYC",),
        salary_floor=80000,
        needs_sponsorship="unknown",
    )
    return ProfileInput(**(base | kw))  # type: ignore[arg-type]


def mi(
    j: JobInput | None = None, ln: LaneInput | None = None, p: ProfileInput | None = None
) -> MatchInput:
    return MatchInput(job=j or job(), lane=ln or lane(), profile=p or profile())
