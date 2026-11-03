"""Applications, generated documents, claim maps and application history.

Document contents live in private files under DATA_DIR/documents; the database
keeps hashes, metadata and the claim map.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from careeros.common.clock import utcnow
from careeros.common.ids import new_id
from careeros.db.base import Base, UTCDateTime


class Application(Base):
    __tablename__ = "application"
    __table_args__ = (
        UniqueConstraint("job_id"),
        Index("ix_application_status", "status"),
        Index("ix_application_next_follow_up_at", "next_follow_up_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("job.id"), nullable=False)
    role_lane_id: Mapped[str | None] = mapped_column(
        ForeignKey("role_lane.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="preparing")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    outcome: Mapped[str | None] = mapped_column(String(30))
    notes: Mapped[str | None] = mapped_column(Text)


class Document(Base):
    __tablename__ = "document"
    __table_args__ = (UniqueConstraint("application_id", "document_type", "version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_type: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    base_template_id: Mapped[str] = mapped_column(String(100), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(30), nullable=False, default="none")
    model_name: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # blocked|needs_ack|ready
    qa_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    warnings_acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class DocumentClaim(Base):
    __tablename__ = "document_claim"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("document.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section: Mapped[str] = mapped_column(String(30), nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_profile_fact_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False)
    warning: Mapped[str | None] = mapped_column(Text)


class ApplicationEvent(Base):
    __tablename__ = "application_event"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
