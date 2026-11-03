"""Candidate profile, facts, skills, experience, projects, lanes, work authorization.

All rows here are entered or confirmed by the user. Nothing is inferred.
`verified_status` separates facts the user has confirmed from drafts; only
verified facts may be used in anything that leaves the app (later phases).
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from careeros.common.clock import utcnow
from careeros.common.ids import new_id
from careeros.db.base import Base, UTCDateTime

VERIFIED = "verified"
UNVERIFIED = "unverified"
VERIFIED_STATUSES = (VERIFIED, UNVERIFIED)


class CandidateProfile(Base):
    __tablename__ = "candidate_profile"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    current_location: Mapped[str | None] = mapped_column(String(200))
    relocation_preferences_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    graduation_date: Mapped[date | None] = mapped_column(Date)
    availability_date: Mapped[date | None] = mapped_column(Date)
    salary_floor: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class ProfileFact(Base):
    __tablename__ = "profile_fact"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_profile.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    fact_key: Mapped[str] = mapped_column(String(100), nullable=False)
    fact_value: Mapped[str] = mapped_column(Text, nullable=False)
    verified_status: Mapped[str] = mapped_column(String(20), nullable=False, default=UNVERIFIED)
    source_note: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class Skill(Base):
    __tablename__ = "skill"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    canonical_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    aliases_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class CandidateSkill(Base):
    __tablename__ = "candidate_skill"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_profile.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[str] = mapped_column(
        ForeignKey("skill.id", ondelete="CASCADE"), primary_key=True
    )
    proficiency: Mapped[str | None] = mapped_column(String(30))
    evidence_fact_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    last_used_year: Mapped[int | None] = mapped_column(Integer)
    verified_status: Mapped[str] = mapped_column(String(20), nullable=False, default=UNVERIFIED)


class Experience(Base):
    __tablename__ = "experience"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_profile.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    verified_status: Mapped[str] = mapped_column(String(20), nullable=False, default=UNVERIFIED)


class Project(Base):
    __tablename__ = "project"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_profile.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    technologies_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    outcomes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence_notes: Mapped[str | None] = mapped_column(Text)
    verified_status: Mapped[str] = mapped_column(String(20), nullable=False, default=UNVERIFIED)


class RoleLane(Base):
    __tablename__ = "role_lane"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rules_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    scoring_weights_json: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False, default=dict)
    resume_template_id: Mapped[str | None] = mapped_column(String(32))


class WorkAuthorizationProfile(Base):
    """User-entered work authorization. Sensitive: never log values.

    The app never infers or determines legal eligibility. Unknown stays unknown.
    """

    __tablename__ = "work_authorization_profile"
    __table_args__ = (UniqueConstraint("profile_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_profile.id", ondelete="CASCADE"), nullable=False
    )
    status_text: Mapped[str | None] = mapped_column(String(200))
    requires_sponsorship_now: Mapped[str] = mapped_column(
        String(10), nullable=False, default="unknown"
    )
    requires_sponsorship_future: Mapped[str] = mapped_column(
        String(10), nullable=False, default="unknown"
    )
    authorized_until: Mapped[date | None] = mapped_column(Date)
    constraints: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
