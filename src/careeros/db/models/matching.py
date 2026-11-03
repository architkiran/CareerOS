"""Deterministic match results per job and role lane, and user overrides.

Overrides live in their own table so rescoring never erases a user's decision.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from careeros.common.clock import utcnow
from careeros.common.ids import new_id
from careeros.db.base import Base, UTCDateTime


class JobLaneMatch(Base):
    __tablename__ = "job_lane_match"
    __table_args__ = (
        UniqueConstraint("job_id", "role_lane_id"),
        Index("ix_job_lane_match_lane_score", "role_lane_id", "score"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("job.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_lane_id: Mapped[str] = mapped_column(
        ForeignKey("role_lane.id", ondelete="CASCADE"), nullable=False
    )
    classified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    eligibility: Mapped[str] = mapped_column(String(10), nullable=False)  # pass | fail | unknown
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    completeness: Mapped[int] = mapped_column(Integer, nullable=False)  # % of weight with data
    score_breakdown_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    hard_filter_results_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class MatchOverride(Base):
    __tablename__ = "match_override"
    __table_args__ = (UniqueConstraint("job_id", "role_lane_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), nullable=False)
    role_lane_id: Mapped[str] = mapped_column(
        ForeignKey("role_lane.id", ondelete="CASCADE"), nullable=False
    )
    eligibility: Mapped[str | None] = mapped_column(String(10))  # pass | fail
    score: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
