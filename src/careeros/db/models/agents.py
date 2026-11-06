"""Durable missions, bounded agent runs, dependency edges and attempt history."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from careeros.common.clock import utcnow
from careeros.common.ids import new_id
from careeros.db.base import Base, UTCDateTime


class Mission(Base):
    __tablename__ = "mission"
    __table_args__ = (
        Index("ix_mission_created_at", "created_at"),
        Index(
            "uq_mission_active_workflow",
            "workflow",
            unique=True,
            sqlite_where=text("status IN ('queued', 'running', 'paused')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workflow: Mapped[str] = mapped_column(String(60), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AgentRun(Base):
    __tablename__ = "agent_run"
    __table_args__ = (UniqueConstraint("mission_id", "agent_key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    mission_id: Mapped[str] = mapped_column(ForeignKey("mission.id"), nullable=False, index=True)
    agent_key: Mapped[str] = mapped_column(String(40), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="blocked")
    task_id: Mapped[str | None] = mapped_column(ForeignKey("task.id"), unique=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    summary: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AgentDependency(Base):
    __tablename__ = "agent_dependency"

    run_id: Mapped[str] = mapped_column(ForeignKey("agent_run.id"), primary_key=True)
    depends_on_id: Mapped[str] = mapped_column(ForeignKey("agent_run.id"), primary_key=True)


class AgentAttempt(Base):
    __tablename__ = "agent_attempt"
    __table_args__ = (UniqueConstraint("run_id", "number"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_run.id"), nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    error: Mapped[str | None] = mapped_column(Text)
