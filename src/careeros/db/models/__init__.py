"""ORM models. Import every model here so Alembic autogenerate sees it."""

from careeros.db.models.jobs import Company, Job, JobSourceRecord, Source, SourceRun
from careeros.db.models.operations import ActivityEvent, PipelineRun, Setting, Task
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
    "Company",
    "Experience",
    "Job",
    "PipelineRun",
    "JobSourceRecord",
    "ProfileFact",
    "Project",
    "RoleLane",
    "Setting",
    "Skill",
    "Source",
    "SourceRun",
    "Task",
    "WorkAuthorizationProfile",
]
