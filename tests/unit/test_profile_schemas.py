from datetime import date

import pytest
from pydantic import ValidationError

from careeros.modules.profile.defaults import DEFAULT_LANES
from careeros.modules.profile.schemas import (
    ExperienceIn,
    FactIn,
    LaneRules,
    LaneWeights,
    ProfileExport,
    ProfileIn,
    SkillIn,
    WorkAuthorizationIn,
)


def test_default_weights_match_spec_and_total_100() -> None:
    w = LaneWeights()
    assert w.model_dump() == {
        "role_title": 20,
        "skills": 25,
        "experience": 20,
        "seniority": 10,
        "location": 10,
        "compensation": 5,
        "preference": 10,
    }


def test_weights_must_total_100() -> None:
    with pytest.raises(ValidationError, match="add up to 100"):
        LaneWeights(skills=30)


def test_weights_reject_negative() -> None:
    with pytest.raises(ValidationError):
        LaneWeights(skills=-5, role_title=50)


def test_default_lanes_valid_and_unique() -> None:
    names = [lane.name.lower() for lane in DEFAULT_LANES]
    assert len(DEFAULT_LANES) == 6
    assert len(set(names)) == len(names)
    for lane in DEFAULT_LANES:
        assert lane.rules.employment_types == ["full_time"]
        assert "internship" in lane.rules.excluded_terms


def test_lane_rules_default_full_time_only() -> None:
    assert LaneRules().employment_types == ["full_time"]


def test_lane_rules_reject_unknown_seniority() -> None:
    with pytest.raises(ValidationError):
        LaneRules(seniority_allowed=["wizard"])  # type: ignore[list-item]


def test_experience_end_before_start_rejected() -> None:
    with pytest.raises(ValidationError, match="End date"):
        ExperienceIn(
            organization="A", title="B", start_date=date(2024, 5, 1), end_date=date(2024, 1, 1)
        )


def test_experience_open_ended_ok() -> None:
    assert ExperienceIn(organization="A", title="B", start_date=date(2024, 5, 1)).end_date is None


def test_invalid_email_rejected() -> None:
    with pytest.raises(ValidationError, match="valid email"):
        ProfileIn(email="not-an-email")


def test_relocation_locations_deduped_case_insensitive() -> None:
    p = ProfileIn(relocation_locations=["NYC", "nyc", " Boston "])
    assert p.relocation_locations == ["NYC", "Boston"]


def test_unknown_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        ProfileIn(display_name="x", gpa="4.0")  # type: ignore[call-arg]


def test_fact_requires_value_and_known_category() -> None:
    with pytest.raises(ValidationError):
        FactIn(category="education", fact_key="Degree", fact_value="   ")
    with pytest.raises(ValidationError):
        FactIn(category="gossip", fact_key="x", fact_value="y")  # type: ignore[arg-type]


def test_fact_defaults_to_unverified() -> None:
    assert FactIn(category="other", fact_key="k", fact_value="v").verified_status == "unverified"


def test_skill_year_bounds() -> None:
    with pytest.raises(ValidationError):
        SkillIn(name="SQL", last_used_year=1800)


def test_work_authorization_defaults_unknown_and_unconfirmed() -> None:
    wa = WorkAuthorizationIn()
    assert wa.requires_sponsorship_now == "unknown"
    assert wa.requires_sponsorship_future == "unknown"
    assert wa.confirmed is False


def test_work_authorization_rejects_free_values() -> None:
    with pytest.raises(ValidationError):
        WorkAuthorizationIn(requires_sponsorship_now="maybe")  # type: ignore[arg-type]


def test_export_rejects_future_schema_version() -> None:
    with pytest.raises(ValidationError):
        ProfileExport.model_validate({"schema_version": 2, "profile": {}})
