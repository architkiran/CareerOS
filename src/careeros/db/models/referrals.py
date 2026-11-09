"""User-recorded paths to a referral. No external action is inferred or automated."""

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from careeros.common.clock import utcnow
from careeros.common.ids import new_id
from careeros.db.base import Base, UTCDateTime


class ReferralPath(Base):
    __tablename__ = "referral_path"
    __table_args__ = (UniqueConstraint("job_id", "contact_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("outreach_contact.id", ondelete="CASCADE"), index=True
    )
    relationship: Mapped[str] = mapped_column(String(30), nullable=False)
    via: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="identified")
    notes: Mapped[str | None] = mapped_column(Text)
    draft_id: Mapped[str | None] = mapped_column(
        ForeignKey("outreach_draft.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
