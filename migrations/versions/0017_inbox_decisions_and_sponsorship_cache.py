"""Shortlist decisions and a derived, expiring sponsorship display cache."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job", sa.Column("saved_stage", sa.String(20)))
    op.add_column("job", sa.Column("next_action", sa.String(500)))
    op.add_column(
        "job",
        sa.Column(
            "sponsorship_status", sa.String(20), nullable=False, server_default="not_indicated"
        ),
    )
    op.add_column(
        "job",
        sa.Column("sponsorship_evidence_json", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column("job", sa.Column("sponsorship_checked_at", sa.DateTime(timezone=True)))
    op.add_column("job", sa.Column("sponsorship_valid_until", sa.DateTime(timezone=True)))
    op.execute(
        "UPDATE job SET saved_stage = 'saved' WHERE triage_status IN ('saved','shortlisted')"
    )


def downgrade() -> None:
    with op.batch_alter_table("job") as batch:
        for col in (
            "saved_stage",
            "next_action",
            "sponsorship_status",
            "sponsorship_evidence_json",
            "sponsorship_checked_at",
            "sponsorship_valid_until",
        ):
            batch.drop_column(col)
