from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from careeros.db.models import ActivityEvent, CandidateProfile, ProfileFact, Skill
from careeros.modules.profile import service
from careeros.modules.profile.defaults import DEFAULT_LANES
from careeros.modules.profile.schemas import (
    ExperienceIn,
    FactIn,
    LaneIn,
    LaneWeights,
    ProfileIn,
    ProjectIn,
    SkillIn,
    WorkAuthorizationIn,
)


def _fact(**kw: object) -> FactIn:
    base: dict[str, object] = {"category": "education", "fact_key": "Degree", "fact_value": "MS CS"}
    return FactIn(**(base | kw))  # type: ignore[arg-type]


def test_profile_created_once(session: Session) -> None:
    a = service.get_or_create_profile(session)
    b = service.get_or_create_profile(session)
    session.commit()
    assert a.id == b.id
    assert session.scalars(select(CandidateProfile)).all() == [a]


def test_update_profile_roundtrip(session: Session) -> None:
    data = ProfileIn(
        display_name="Test User",
        open_to_relocation=True,
        relocation_locations=["NYC"],
        graduation_date=date(2026, 12, 15),
        salary_floor=80000,
    )
    service.update_profile(session, data)
    session.commit()
    profile = service.get_profile(session)
    assert profile is not None
    assert service.profile_to_input(profile) == data


def test_fact_verified_at_follows_status(session: Session) -> None:
    fact = service.add_fact(session, _fact(verified_status="verified"))
    assert fact.verified_at is not None
    service.set_verified(session, "facts", fact.id, False)
    assert fact.verified_status == "unverified" and fact.verified_at is None
    service.set_verified(session, "facts", fact.id, True)
    assert fact.verified_at is not None


def test_verified_only_filter(session: Session) -> None:
    service.add_fact(session, _fact(fact_key="A", verified_status="verified"))
    service.add_fact(session, _fact(fact_key="B"))
    profile = service.get_or_create_profile(session)
    assert [f.fact_key for f in service.list_facts(session, profile.id, verified_only=True)] == [
        "A"
    ]
    assert len(service.list_facts(session, profile.id)) == 2


def test_skill_matched_case_insensitively_and_by_alias(session: Session) -> None:
    session.add(Skill(canonical_name="PostgreSQL", aliases_json=["postgres", "psql"]))
    session.flush()
    service.add_skill(session, SkillIn(name="postgres"))
    profile = service.get_or_create_profile(session)
    assert [s.name for s in service.list_skills(session, profile.id)] == ["PostgreSQL"]
    assert len(session.scalars(select(Skill)).all()) == 1


def test_duplicate_skill_rejected(session: Session) -> None:
    service.add_skill(session, SkillIn(name="SQL"))
    session.flush()
    with pytest.raises(service.ConflictError, match="already"):
        service.add_skill(session, SkillIn(name="sql"))


def test_skill_verify_and_delete(session: Session) -> None:
    cs = service.add_skill(session, SkillIn(name="Python"))
    session.flush()
    service.set_verified(session, "skills", cs.skill_id, True)
    profile = service.get_or_create_profile(session)
    assert service.list_skills(session, profile.id, verified_only=True)[0].name == "Python"
    service.delete_item(session, "skills", cs.skill_id)
    session.flush()
    assert service.list_skills(session, profile.id) == []


def test_verify_missing_item_raises(session: Session) -> None:
    for kind in ("facts", "skills", "experience", "projects"):
        with pytest.raises(service.NotFoundError):
            service.set_verified(session, kind, "nope", True)  # type: ignore[arg-type]
        with pytest.raises(service.NotFoundError):
            service.delete_item(session, kind, "nope")  # type: ignore[arg-type]


def test_cannot_touch_item_from_another_profile(session: Session) -> None:
    current = service.get_or_create_profile(session)
    session.flush()
    other = CandidateProfile(display_name="other")
    session.add(other)
    session.flush()
    stray = ProfileFact(profile_id=other.id, category="other", fact_key="k", fact_value="v")
    session.add(stray)
    session.flush()
    assert service.get_or_create_profile(session).id == current.id
    with pytest.raises(service.NotFoundError):
        service.set_verified(session, "facts", stray.id, True)
    with pytest.raises(service.NotFoundError):
        service.delete_item(session, "facts", stray.id)


def test_experience_and_project_listing(session: Session) -> None:
    service.add_experience(
        session, ExperienceIn(organization="Org", title="Analyst", start_date=date(2023, 1, 1))
    )
    service.add_experience(
        session, ExperienceIn(organization="Org2", title="Intern", start_date=date(2021, 1, 1))
    )
    service.add_project(session, ProjectIn(name="P", technologies=["SQL"], outcomes=["Built X"]))
    profile = service.get_or_create_profile(session)
    assert [e.title for e in service.list_experience(session, profile.id)] == ["Analyst", "Intern"]
    assert service.list_projects(session, profile.id)[0].technologies_json == ["SQL"]


def test_default_lanes_idempotent_and_preserve_edits(session: Session) -> None:
    assert service.add_default_lanes(session) == 6
    lane = service.list_lanes(session)[0]
    edited = LaneIn(
        name=lane.name,
        enabled=False,
        weights=LaneWeights(
            role_title=40,
            skills=25,
            experience=0,
            seniority=10,
            location=10,
            compensation=5,
            preference=10,
        ),
    )
    service.update_lane(session, lane.id, edited)
    assert service.add_default_lanes(session) == 0
    again = service.list_lanes(session)[0]
    assert again.enabled is False
    assert service.lane_weights(again).role_title == 40


def test_lane_name_conflicts(session: Session) -> None:
    service.create_lane(session, LaneIn(name="Alpha"))
    b = service.create_lane(session, LaneIn(name="Beta"))
    with pytest.raises(service.ConflictError):
        service.create_lane(session, LaneIn(name="alpha"))
    with pytest.raises(service.ConflictError):
        service.update_lane(session, b.id, LaneIn(name="ALPHA"))
    with pytest.raises(service.NotFoundError):
        service.update_lane(session, "missing", LaneIn(name="Gamma"))


def test_enabled_only_lanes(session: Session) -> None:
    a = service.create_lane(session, LaneIn(name="A"))
    service.create_lane(session, LaneIn(name="B"))
    service.set_lane_enabled(session, a.id, False)
    assert [lane.name for lane in service.list_lanes(session, enabled_only=True)] == ["B"]


def test_work_authorization_saved_without_values_in_events(session: Session) -> None:
    private_status = "SECRET-STATUS-TEXT"
    service.save_work_authorization(
        session,
        WorkAuthorizationIn(
            status_text=private_status,
            requires_sponsorship_now="no",
            notes="SECRET-NOTE",
            confirmed=True,
        ),
    )
    session.commit()
    profile = service.get_or_create_profile(session)
    wa = service.get_work_authorization(session, profile.id)
    assert wa is not None and wa.verified_at is not None
    for e in session.scalars(select(ActivityEvent)):
        blob = f"{e.message} {e.metadata_json}"
        assert "SECRET" not in blob


def test_work_authorization_unconfirmed_clears_verified_at(session: Session) -> None:
    service.save_work_authorization(session, WorkAuthorizationIn(confirmed=True))
    wa = service.save_work_authorization(session, WorkAuthorizationIn(confirmed=False))
    assert wa.verified_at is None


def test_summary_gaps(session: Session) -> None:
    empty = service.profile_summary(session)
    assert empty.exists is False and "Create your profile" in empty.gaps
    service.update_profile(session, ProfileIn(display_name="X"))
    service.add_fact(session, _fact(verified_status="verified"))
    service.add_fact(session, _fact(fact_key="Other"))
    s = service.profile_summary(session)
    assert (s.verified, s.unverified) == (1, 1)
    assert "Add skills" in s.gaps and "Enable at least one role lane" in s.gaps
    assert "Enter and confirm work authorization" in s.gaps


def _populate(session: Session) -> None:
    service.update_profile(session, ProfileIn(display_name="Roundtrip", email="a@b.co"))
    service.add_fact(session, _fact(verified_status="verified", source_note="transcript"))
    service.add_skill(
        session, SkillIn(name="SQL", proficiency="advanced", verified_status="verified")
    )
    service.add_experience(session, ExperienceIn(organization="Org", title="Analyst"))
    service.add_project(session, ProjectIn(name="Proj", technologies=["Python"]))
    service.add_default_lanes(session)
    service.save_work_authorization(session, WorkAuthorizationIn(status_text="S", confirmed=True))
    session.commit()


def test_export_excludes_work_authorization_by_default(session: Session) -> None:
    _populate(session)
    assert service.export_profile(session).work_authorization is None
    full = service.export_profile(session, include_work_authorization=True)
    assert full.work_authorization is not None and full.work_authorization.status_text == "S"


def test_export_with_no_profile_raises(session: Session) -> None:
    with pytest.raises(service.NotFoundError):
        service.export_profile(session)


def test_import_refuses_overwrite_without_replace(session: Session) -> None:
    _populate(session)
    data = service.export_profile(session)
    with pytest.raises(service.ConflictError):
        service.import_profile(session, data)


def test_import_replace_roundtrip(session: Session) -> None:
    _populate(session)
    exported = service.export_profile(session, include_work_authorization=True)
    service.import_profile(session, exported, replace=True)
    session.commit()
    again = service.export_profile(session, include_work_authorization=True)
    assert again.model_dump(exclude={"exported_at"}) == exported.model_dump(exclude={"exported_at"})
    assert len(session.scalars(select(CandidateProfile)).all()) == 1


def test_import_into_empty_database(session: Session) -> None:
    _populate(session)
    exported = service.export_profile(session)
    session.execute(CandidateProfile.__table__.delete())
    session.commit()
    service.import_profile(session, exported)
    session.commit()
    profile = service.get_profile(session)
    assert profile is not None and profile.display_name == "Roundtrip"


def test_import_failure_leaves_data_unchanged(session: Session) -> None:
    _populate(session)
    exported = service.export_profile(session)
    bad = exported.model_copy(update={"skills": [SkillIn(name="SQL"), SkillIn(name="sql")]})
    with pytest.raises(service.ConflictError):
        service.import_profile(session, bad, replace=True)
    session.rollback()
    profile = service.get_profile(session)
    assert profile is not None and profile.display_name == "Roundtrip"
    assert len(service.list_facts(session, profile.id)) == 1


def test_default_lane_names_are_spec_families() -> None:
    assert "Data Engineering (selective)" in [lane.name for lane in DEFAULT_LANES]
