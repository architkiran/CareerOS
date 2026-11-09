"""ORM models. Import every model here so Alembic autogenerate sees it."""

from careeros.db.models.agents import AgentAttempt, AgentDependency, AgentRun, Mission
from careeros.db.models.applications import Application, ApplicationEvent, Document, DocumentClaim
from careeros.db.models.approvals import Approval, FollowUp, OutreachContact, OutreachDraft
from careeros.db.models.interviews import InterviewAnswer, InterviewPlan
from careeros.db.models.jobs import Company, Job, JobSourceRecord, Source, SourceRun
from careeros.db.models.market import MarketBrief
from careeros.db.models.matching import JobLaneMatch, MatchOverride
from careeros.db.models.operations import (
    ActivityEvent,
    ModelCache,
    ModelUsage,
    PipelineRun,
    Setting,
    Task,
)
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
from careeros.db.models.referrals import ReferralPath
from careeros.db.models.research import Evidence, ResearchItem

__all__ = [
    "ReferralPath",
    "InterviewAnswer",
    "InterviewPlan",
    "MarketBrief",
    "AgentAttempt",
    "AgentDependency",
    "AgentRun",
    "Mission",
    "Approval",
    "FollowUp",
    "OutreachContact",
    "OutreachDraft",
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
    "ModelCache",
    "ModelUsage",
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
