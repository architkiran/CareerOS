"""Persist source-linked referral paths without changing existing contacts or applications."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "referral_path",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "job_id", sa.String(32), sa.ForeignKey("job.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "contact_id",
            sa.String(32),
            sa.ForeignKey("outreach_contact.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relationship", sa.String(30), nullable=False),
        sa.Column("via", sa.String(200)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "draft_id", sa.String(32), sa.ForeignKey("outreach_draft.id", ondelete="SET NULL")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "contact_id"),
    )
    op.create_index("ix_referral_path_job_id", "referral_path", ["job_id"])
    op.create_index("ix_referral_path_contact_id", "referral_path", ["contact_id"])


def downgrade() -> None:
    op.drop_table("referral_path")
