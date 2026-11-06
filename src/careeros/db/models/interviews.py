"""Private interview practice. Preparation never changes application status or profile facts."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from careeros.common.clock import utcnow
from careeros.common.ids import new_id
from careeros.db.base import Base, UTCDateTime


class InterviewPlan(Base):
    __tablename__ = "interview_plan"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("job.id"), nullable=False, index=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="practice")
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    feedback: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class InterviewAnswer(Base):
    __tablename__ = "interview_answer"
    __table_args__ = (UniqueConstraint("plan_id", "question_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("interview_plan.id"), nullable=False, index=True
    )
    question_id: Mapped[str] = mapped_column(String(40), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[int | None] = mapped_column(Integer)
    reflection: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
