"""Profile service functions. Routes and other modules call these, not the ORM directly."""

from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import (
    CandidateProfile,
    CandidateSkill,
    Experience,
    ProfileFact,
    Project,
    RoleLane,
    Skill,
    WorkAuthorizationProfile,
)
from careeros.db.models.profile import VERIFIED
from careeros.modules.events.service import record_event
from careeros.modules.profile.defaults import DEFAULT_LANES
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

ItemKind = Literal["facts", "skills", "experience", "projects"]


class NotFoundError(LookupError):
    pass


class ConflictError(ValueError):
    pass


# ---------- profile ----------


def get_profile(session: Session) -> CandidateProfile | None:
    return session.scalars(select(CandidateProfile).order_by(CandidateProfile.created_at)).first()


def get_or_create_profile(session: Session) -> CandidateProfile:
    profile = get_profile(session)
    if profile is None:
        profile = CandidateProfile()
        session.add(profile)
        session.flush()
        record_event(
            session,
            "profile.created",
            "Candidate profile created",
            entity_type="profile",
            entity_id=profile.id,
        )
    return profile


def update_profile(session: Session, data: ProfileIn) -> CandidateProfile:
    profile = get_or_create_profile(session)
    profile.display_name = data.display_name
    profile.email = data.email
    profile.phone = data.phone
    profile.current_location = data.current_location
    profile.relocation_preferences_json = {
        "open_to_relocation": data.open_to_relocation,
        "locations": data.relocation_locations,
    }
    profile.graduation_date = data.graduation_date
    profile.availability_date = data.availability_date
    profile.salary_floor = data.salary_floor
    record_event(
        session,
        "profile.updated",
        "Profile basics updated",
        entity_type="profile",
        entity_id=profile.id,
    )
    return profile


def profile_to_input(profile: CandidateProfile) -> ProfileIn:
    reloc = profile.relocation_preferences_json or {}
    return ProfileIn(
        display_name=profile.display_name,
        email=profile.email,
        phone=profile.phone,
        current_location=profile.current_location,
        open_to_relocation=reloc.get("open_to_relocation"),
        relocation_locations=reloc.get("locations", []),
        graduation_date=profile.graduation_date,
        availability_date=profile.availability_date,
        salary_floor=profile.salary_floor,
    )


# ---------- facts ----------


def add_fact(session: Session, data: FactIn) -> ProfileFact:
    profile = get_or_create_profile(session)
    fact = ProfileFact(
        profile_id=profile.id,
        category=data.category,
        fact_key=data.fact_key,
        fact_value=data.fact_value,
        source_note=data.source_note,
        verified_status=data.verified_status,
        verified_at=utcnow() if data.verified_status == VERIFIED else None,
    )
    session.add(fact)
    session.flush()
    record_event(
        session,
        "profile.fact_added",
        f"Fact added ({data.category})",
        entity_type="profile_fact",
        entity_id=fact.id,
        metadata={"verified_status": data.verified_status},
    )
    return fact


def list_facts(
    session: Session, profile_id: str, *, verified_only: bool = False
) -> list[ProfileFact]:
    stmt = select(ProfileFact).where(ProfileFact.profile_id == profile_id)
    if verified_only:
        stmt = stmt.where(ProfileFact.verified_status == VERIFIED)
    return list(session.scalars(stmt.order_by(ProfileFact.category, ProfileFact.created_at)))


# ---------- skills ----------


def find_skill(session: Session, name: str) -> Skill | None:
    """Match a skill by canonical name or alias, case-insensitively."""
    key = name.strip().lower()
    found = session.scalars(select(Skill).where(func.lower(Skill.canonical_name) == key)).first()
    if found:
        return found
    for skill in session.scalars(select(Skill)):
        if key in (a.lower() for a in skill.aliases_json):
            return skill
    return None


def add_skill(session: Session, data: SkillIn) -> CandidateSkill:
    profile = get_or_create_profile(session)
    skill = find_skill(session, data.name)
    if skill is None:
        skill = Skill(canonical_name=data.name, aliases_json=[])
        session.add(skill)
        session.flush()
    existing = session.get(CandidateSkill, (profile.id, skill.id))
    if existing is not None:
        raise ConflictError(f"Skill '{skill.canonical_name}' is already on your profile.")
    cs = CandidateSkill(
        profile_id=profile.id,
        skill_id=skill.id,
        proficiency=data.proficiency,
        last_used_year=data.last_used_year,
        verified_status=data.verified_status,
        evidence_fact_ids_json=[],
    )
    session.add(cs)
    record_event(
        session,
        "profile.skill_added",
        f"Skill added: {skill.canonical_name}",
        entity_type="skill",
        entity_id=skill.id,
    )
    return cs


@dataclass
class SkillRow:
    skill_id: str
    name: str
    proficiency: str | None
    last_used_year: int | None
    verified_status: str


def list_skills(
    session: Session, profile_id: str, *, verified_only: bool = False
) -> list[SkillRow]:
    stmt = (
        select(CandidateSkill, Skill)
        .join(Skill, Skill.id == CandidateSkill.skill_id)
        .where(CandidateSkill.profile_id == profile_id)
        .order_by(func.lower(Skill.canonical_name))
    )
    if verified_only:
        stmt = stmt.where(CandidateSkill.verified_status == VERIFIED)
    return [
        SkillRow(s.id, s.canonical_name, cs.proficiency, cs.last_used_year, cs.verified_status)
        for cs, s in session.execute(stmt)
    ]


# ---------- experience / projects ----------


def add_experience(session: Session, data: ExperienceIn) -> Experience:
    profile = get_or_create_profile(session)
    exp = Experience(profile_id=profile.id, **data.model_dump())
    session.add(exp)
    session.flush()
    record_event(
        session,
        "profile.experience_added",
        f"Experience added: {exp.title}",
        entity_type="experience",
        entity_id=exp.id,
    )
    return exp


def list_experience(session: Session, profile_id: str) -> list[Experience]:
    stmt = (
        select(Experience)
        .where(Experience.profile_id == profile_id)
        .order_by(Experience.start_date.desc().nulls_last())
    )
    return list(session.scalars(stmt))


def add_project(session: Session, data: ProjectIn) -> Project:
    profile = get_or_create_profile(session)
    proj = Project(
        profile_id=profile.id,
        name=data.name,
        description=data.description,
        technologies_json=data.technologies,
        outcomes_json=data.outcomes,
        evidence_notes=data.evidence_notes,
        verified_status=data.verified_status,
    )
    session.add(proj)
    session.flush()
    record_event(
        session,
        "profile.project_added",
        f"Project added: {proj.name}",
        entity_type="project",
        entity_id=proj.id,
    )
    return proj


def list_projects(session: Session, profile_id: str) -> list[Project]:
    stmt = select(Project).where(Project.profile_id == profile_id).order_by(Project.name)
    return list(session.scalars(stmt))


# ---------- verify / delete (shared) ----------


def _load_item(
    session: Session, kind: ItemKind, item_id: str, profile_id: str
) -> ProfileFact | CandidateSkill | Experience | Project:
    item: ProfileFact | CandidateSkill | Experience | Project | None
    if kind == "skills":
        item = session.get(CandidateSkill, (profile_id, item_id))
    else:
        found: ProfileFact | Experience | Project | None
        if kind == "facts":
            found = session.get(ProfileFact, item_id)
        elif kind == "experience":
            found = session.get(Experience, item_id)
        else:
            found = session.get(Project, item_id)
        item = found if found is not None and found.profile_id == profile_id else None
    if item is None:
        raise NotFoundError(f"{kind} item not found")
    return item


def set_verified(session: Session, kind: ItemKind, item_id: str, verified: bool) -> None:
    profile = get_or_create_profile(session)
    item = _load_item(session, kind, item_id, profile.id)
    item.verified_status = VERIFIED if verified else "unverified"
    if isinstance(item, ProfileFact):
        item.verified_at = utcnow() if verified else None
    record_event(
        session,
        "profile.verification_changed",
        f"{kind.rstrip('s').capitalize()} marked {item.verified_status}",
        entity_type=kind,
        entity_id=item_id,
    )


def delete_item(session: Session, kind: ItemKind, item_id: str) -> None:
    profile = get_or_create_profile(session)
    item = _load_item(session, kind, item_id, profile.id)
    session.delete(item)
    record_event(
        session,
        "profile.item_deleted",
        f"{kind.rstrip('s').capitalize()} deleted",
        entity_type=kind,
        entity_id=item_id,
    )


# ---------- role lanes ----------


def list_lanes(session: Session, *, enabled_only: bool = False) -> list[RoleLane]:
    stmt = select(RoleLane).order_by(RoleLane.name)
    if enabled_only:
        stmt = stmt.where(RoleLane.enabled.is_(True))
    return list(session.scalars(stmt))


def lane_rules(lane: RoleLane) -> LaneRules:
    return LaneRules.model_validate(lane.rules_json)


def lane_weights(lane: RoleLane) -> LaneWeights:
    return LaneWeights.model_validate(lane.scoring_weights_json)


def _lane_by_name(session: Session, name: str) -> RoleLane | None:
    return session.scalars(
        select(RoleLane).where(func.lower(RoleLane.name) == name.lower())
    ).first()


def create_lane(session: Session, data: LaneIn) -> RoleLane:
    if _lane_by_name(session, data.name):
        raise ConflictError(f"A lane named '{data.name}' already exists.")
    lane = RoleLane(
        name=data.name,
        enabled=data.enabled,
        rules_json=data.rules.model_dump(),
        scoring_weights_json=data.weights.model_dump(),
    )
    session.add(lane)
    session.flush()
    record_event(
        session,
        "lane.created",
        f"Role lane created: {lane.name}",
        entity_type="role_lane",
        entity_id=lane.id,
    )
    return lane


def update_lane(session: Session, lane_id: str, data: LaneIn) -> RoleLane:
    lane = session.get(RoleLane, lane_id)
    if lane is None:
        raise NotFoundError("Role lane not found")
    clash = _lane_by_name(session, data.name)
    if clash is not None and clash.id != lane.id:
        raise ConflictError(f"A lane named '{data.name}' already exists.")
    lane.name = data.name
    lane.enabled = data.enabled
    lane.rules_json = data.rules.model_dump()
    lane.scoring_weights_json = data.weights.model_dump()
    record_event(
        session,
        "lane.updated",
        f"Role lane updated: {lane.name}",
        entity_type="role_lane",
        entity_id=lane.id,
    )
    return lane


def set_lane_enabled(session: Session, lane_id: str, enabled: bool) -> RoleLane:
    lane = session.get(RoleLane, lane_id)
    if lane is None:
        raise NotFoundError("Role lane not found")
    lane.enabled = enabled
    record_event(
        session,
        "lane.updated",
        f"Role lane {'enabled' if enabled else 'disabled'}: {lane.name}",
        entity_type="role_lane",
        entity_id=lane.id,
    )
    return lane


def add_default_lanes(session: Session) -> int:
    """Insert any default lanes that are missing. Never overwrites user edits."""
    added = 0
    for lane in DEFAULT_LANES:
        if _lane_by_name(session, lane.name) is None:
            create_lane(session, lane)
            added += 1
    return added


# ---------- work authorization (sensitive) ----------


def get_work_authorization(session: Session, profile_id: str) -> WorkAuthorizationProfile | None:
    stmt = select(WorkAuthorizationProfile).where(WorkAuthorizationProfile.profile_id == profile_id)
    return session.scalars(stmt).first()


def save_work_authorization(
    session: Session, data: WorkAuthorizationIn
) -> WorkAuthorizationProfile:
    profile = get_or_create_profile(session)
    wa = get_work_authorization(session, profile.id)
    if wa is None:
        wa = WorkAuthorizationProfile(profile_id=profile.id)
        session.add(wa)
    wa.status_text = data.status_text
    wa.requires_sponsorship_now = data.requires_sponsorship_now
    wa.requires_sponsorship_future = data.requires_sponsorship_future
    wa.authorized_until = data.authorized_until
    wa.constraints = data.constraints
    wa.notes = data.notes
    wa.verified_at = utcnow() if data.confirmed else None
    session.flush()
    # Deliberately no values in the event: this data is sensitive.
    record_event(
        session,
        "profile.work_authorization_updated",
        "Work authorization details updated",
        entity_type="work_authorization",
        entity_id=wa.id,
        metadata={"confirmed": data.confirmed},
    )
    return wa


def work_authorization_to_input(wa: WorkAuthorizationProfile) -> WorkAuthorizationIn:
    return WorkAuthorizationIn(
        status_text=wa.status_text,
        requires_sponsorship_now=wa.requires_sponsorship_now,
        requires_sponsorship_future=wa.requires_sponsorship_future,
        authorized_until=wa.authorized_until,
        constraints=wa.constraints,
        notes=wa.notes,
        confirmed=wa.verified_at is not None,
    )


# ---------- summary ----------


@dataclass
class ProfileSummary:
    exists: bool
    verified: int = 0
    unverified: int = 0
    lanes_enabled: int = 0
    work_authorization_set: bool = False
    gaps: list[str] = field(default_factory=list)


def profile_summary(session: Session) -> ProfileSummary:
    profile = get_profile(session)
    lanes_enabled = len(list_lanes(session, enabled_only=True))
    if profile is None:
        return ProfileSummary(False, lanes_enabled=lanes_enabled, gaps=["Create your profile"])
    statuses = [f.verified_status for f in list_facts(session, profile.id)]
    statuses += [s.verified_status for s in list_skills(session, profile.id)]
    statuses += [e.verified_status for e in list_experience(session, profile.id)]
    statuses += [p.verified_status for p in list_projects(session, profile.id)]
    verified = sum(1 for s in statuses if s == VERIFIED)
    wa = get_work_authorization(session, profile.id)
    gaps = []
    if not profile.display_name:
        gaps.append("Add your name")
    if not list_skills(session, profile.id):
        gaps.append("Add skills")
    if lanes_enabled == 0:
        gaps.append("Enable at least one role lane")
    if wa is None or wa.verified_at is None:
        gaps.append("Enter and confirm work authorization")
    return ProfileSummary(
        True,
        verified,
        len(statuses) - verified,
        lanes_enabled,
        wa is not None and wa.verified_at is not None,
        gaps,
    )


# ---------- export / import ----------


def export_profile(session: Session, *, include_work_authorization: bool = False) -> ProfileExport:
    profile = get_profile(session)
    if profile is None:
        raise NotFoundError("No profile to export")
    experiences = list_experience(session, profile.id)
    projects = list_projects(session, profile.id)
    wa = get_work_authorization(session, profile.id) if include_work_authorization else None
    return ProfileExport(
        exported_at=utcnow(),
        profile=profile_to_input(profile),
        facts=[
            FactIn(
                category=f.category,
                fact_key=f.fact_key,
                fact_value=f.fact_value,
                source_note=f.source_note,
                verified_status=f.verified_status,
            )
            for f in list_facts(session, profile.id)
        ],
        skills=[
            SkillIn(
                name=s.name,
                proficiency=s.proficiency,
                last_used_year=s.last_used_year,
                verified_status=s.verified_status,
            )
            for s in list_skills(session, profile.id)
        ],
        experiences=[
            ExperienceIn(
                organization=e.organization,
                title=e.title,
                start_date=e.start_date,
                end_date=e.end_date,
                description=e.description,
                verified_status=e.verified_status,
            )
            for e in experiences
        ],
        projects=[
            ProjectIn(
                name=p.name,
                description=p.description,
                technologies=p.technologies_json,
                outcomes=p.outcomes_json,
                evidence_notes=p.evidence_notes,
                verified_status=p.verified_status,
            )
            for p in projects
        ],
        lanes=[
            LaneIn(
                name=lane.name,
                enabled=lane.enabled,
                rules=lane_rules(lane),
                weights=lane_weights(lane),
            )
            for lane in list_lanes(session)
        ],
        work_authorization=work_authorization_to_input(wa) if wa else None,
    )


def has_profile_content(session: Session) -> bool:
    profile = get_profile(session)
    if profile is None:
        return False
    return bool(
        profile.display_name
        or list_facts(session, profile.id)
        or list_skills(session, profile.id)
        or list_experience(session, profile.id)
        or list_projects(session, profile.id)
    )


def import_profile(session: Session, data: ProfileExport, *, replace: bool = False) -> None:
    """Load an exported profile. Refuses to overwrite existing data unless `replace`.

    Runs in the caller's transaction, so a failure leaves the database unchanged.
    """
    if has_profile_content(session) and not replace:
        raise ConflictError(
            "A profile already exists. Tick 'replace existing profile' to overwrite it."
        )
    existing = get_profile(session)
    if existing is not None:
        session.delete(existing)  # cascades to facts, skills, experience, projects, work auth
        session.flush()
    update_profile(session, data.profile)
    for fact in data.facts:
        add_fact(session, fact)
    for skill in data.skills:
        add_skill(session, skill)
    for exp in data.experiences:
        add_experience(session, exp)
    for proj in data.projects:
        add_project(session, proj)
    for lane in data.lanes:
        current = _lane_by_name(session, lane.name)
        if current is None:
            create_lane(session, lane)
        else:
            update_lane(session, current.id, lane)
    if data.work_authorization is not None:
        save_work_authorization(session, data.work_authorization)
    record_event(
        session,
        "profile.imported",
        "Profile imported from JSON",
        metadata={
            "replaced": existing is not None,
            "facts": len(data.facts),
            "skills": len(data.skills),
        },
    )
