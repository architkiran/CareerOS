"""Employer research and evidence.

Every claim keeps its source, dates, excerpt and confidence. Only evidence the
user has accepted, from an official or government source, decides an
employer's policy; third-party sources are shown as leads, never as proof.
"""

from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from careeros.common.clock import utcnow
from careeros.common.ids import new_id
from careeros.db.base import Base, UTCDateTime


class ResearchItem(Base):
    __tablename__ = "research_item"
    __table_args__ = (Index("ix_research_item_status", "status"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)
    research_type: Mapped[str] = mapped_column(String(30), nullable=False, default="sponsorship")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    summary: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (Index("ix_evidence_company_claim", "company_id", "claim_type"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    research_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("research_item.id", ondelete="SET NULL")
    )
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)
    claim_type: Mapped[str] = mapped_column(String(30), nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_title: Mapped[str | None] = mapped_column(String(300))
    source_date: Mapped[date | None] = mapped_column(Date)
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    short_excerpt: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(20), nullable=False)  # job_posting | user
    reviewer_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
