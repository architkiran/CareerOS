"""Companies, sources, source runs, canonical jobs and their source records.

Raw source payloads live in job_source_record, separate from the canonical job
and from anything generated later. Every job keeps full provenance.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from careeros.common.clock import utcnow
from careeros.common.ids import new_id
from careeros.db.base import Base, UTCDateTime

SOURCE_TYPES = ("greenhouse", "lever", "ashby", "smartrecruiters", "remotive", "jobicy", "wwr")


class Company(Base):
    __tablename__ = "company"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    canonical_name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    domain: Mapped[str | None] = mapped_column(String(200))
    careers_url: Mapped[str | None] = mapped_column(String(500))
    company_notes: Mapped[str | None] = mapped_column(Text)


class Source(Base):
    __tablename__ = "source"
    __table_args__ = (UniqueConstraint("source_type", "board_token"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    board_token: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("company.id"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rate_limit_seconds: Mapped[float] = mapped_column(nullable=False, default=2.0)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class SourceRun(Base):
    __tablename__ = "source_run"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source.id", ondelete="CASCADE"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    http_status: Mapped[int | None] = mapped_column(Integer)
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    closed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (
        Index("ix_job_dedupe_key", "dedupe_key"),
        Index("ix_job_first_seen_at", "first_seen_at"),
        Index("ix_job_status", "status"),
        Index("ix_job_company_id", "company_id"),
        Index("ix_job_title", "title"),
        Index("ix_job_canonical_url", "canonical_url"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    canonical_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(300), nullable=False)
    location_text: Mapped[str | None] = mapped_column(String(500))
    workplace_type: Mapped[str | None] = mapped_column(String(20))
    employment_type: Mapped[str | None] = mapped_column(String(20))
    department: Mapped[str | None] = mapped_column(String(200))
    description_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(String(10))
    salary_interval: Mapped[str | None] = mapped_column(String(20))
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    possible_duplicate_of_id: Mapped[str | None] = mapped_column(ForeignKey("job.id"))
    # User triage, separate from the source-driven `status` (active/closed).
    triage_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="new", server_default="new", index=True
    )
    triage_reason: Mapped[str | None] = mapped_column(Text)
    triaged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class JobSourceRecord(Base):
    __tablename__ = "job_source_record"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("job.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    raw_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
