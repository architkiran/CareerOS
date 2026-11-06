"""Immutable, evidence-linked snapshots of the configured job corpus."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from careeros.common.clock import utcnow
from careeros.common.ids import new_id
from careeros.db.base import Base, UTCDateTime


class MarketBrief(Base):
    __tablename__ = "market_brief"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, index=True
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
