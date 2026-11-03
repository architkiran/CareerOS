"""ORM models. Import every model here so Alembic autogenerate sees it."""

from careeros.db.models.operations import ActivityEvent, Setting
from careeros.db.models.profile import (
    CandidateProfile,
    CandidateSkill,
    Experience,
    ProfileFact,
    Project,
    RoleLane,
    Skill,
    WorkAuthorizationProfile,
)

__all__ = [
    "ActivityEvent",
    "CandidateProfile",
    "CandidateSkill",
    "Experience",
    "ProfileFact",
    "Project",
    "RoleLane",
    "Setting",
    "Skill",
    "WorkAuthorizationProfile",
]
