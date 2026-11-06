"""evidence linked market brief snapshots

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-06 06:54:10.864983
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_brief",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("profile_hash", sa.String(length=64), nullable=False),
        sa.Column("report_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_brief")),
        sa.UniqueConstraint("input_hash", name=op.f("uq_market_brief_input_hash")),
    )
    with op.batch_alter_table("market_brief", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_market_brief_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_market_brief_profile_hash"), ["profile_hash"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("market_brief", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_market_brief_profile_hash"))
        batch_op.drop_index(batch_op.f("ix_market_brief_created_at"))

    op.drop_table("market_brief")
