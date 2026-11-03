"""Model gateway usage log and response cache.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-03 11:24:51.366298
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_cache",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("task_name", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_model_cache")),
    )
    op.create_table(
        "model_usage",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("task_name", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost", sa.Double(), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_usage")),
    )
    with op.batch_alter_table("model_usage", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_model_usage_created_at"), ["created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("model_usage", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_model_usage_created_at"))

    op.drop_table("model_usage")
    op.drop_table("model_cache")
