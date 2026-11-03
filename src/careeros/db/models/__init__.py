"""ORM models. Import every model here so Alembic autogenerate sees it."""

from careeros.db.models.applications import Application, ApplicationEvent, Document, DocumentClaim
from careeros.db.models.jobs import Company, Job, JobSourceRecord, Source, SourceRun
from careeros.db.models.matching import JobLaneMatch, MatchOverride
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
from careeros.db.models.research import Evidence, ResearchItem

__all__ = [
    "Application",
    "ApplicationEvent",
    "Document",
    "DocumentClaim",
    "ActivityEvent",
    "CandidateProfile",
    "CandidateSkill",
    "Company",
    "Evidence",
    "Experience",
    "Job",
    "PipelineRun",
    "JobLaneMatch",
    "JobSourceRecord",
    "MatchOverride",
    "ProfileFact",
    "Project",
    "ResearchItem",
    "RoleLane",
    "Setting",
    "Skill",
    "Source",
    "SourceRun",
    "Task",
    "WorkAuthorizationProfile",
]
