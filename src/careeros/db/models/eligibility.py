"""Career OS 2.0: one explainable verdict per job, and aggregated public LCA history."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from careeros.common.clock import utcnow
from careeros.common.ids import new_id
from careeros.db.base import Base, UTCDateTime


class EmployerLcaStat(Base):
    """Certified LCA filings per legal employer name and fiscal year (US DOL disclosure data).

    Historical, employer-level evidence only. It never proves a specific role sponsors.
    """

    __tablename__ = "employer_lca_stat"
    __table_args__ = (
        UniqueConstraint("normalized_name", "fiscal_year"),
        Index("ix_employer_lca_stat_normalized_name", "normalized_name"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    employer_name: Mapped[str] = mapped_column(String(300), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    certified_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_employment: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analyst_like: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    top_titles_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    states_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    last_decision_date: Mapped[str | None] = mapped_column(String(10))
    source_file: Mapped[str] = mapped_column(String(300), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class JobVerdict(Base):
    __tablename__ = "job_verdict"
    __table_args__ = (Index("ix_job_verdict_verdict", "verdict"),)

    job_id: Mapped[str] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), primary_key=True)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    sponsorship_level: Mapped[str] = mapped_column(String(1), nullable=False)
    fit: Mapped[str | None] = mapped_column(String(20))
    role_family: Mapped[str | None] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    next_action: Mapped[str] = mapped_column(Text, nullable=False, default="")
    checks_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    sponsorship_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    fit_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    engine_version: Mapped[str] = mapped_column(String(20), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
