"""Job lane match results and user match overrides.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-03 01:52:55.155848
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_lane_match",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("role_lane_id", sa.String(length=32), nullable=False),
        sa.Column("classified", sa.Boolean(), nullable=False),
        sa.Column("eligibility", sa.String(length=10), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("completeness", sa.Integer(), nullable=False),
        sa.Column("score_breakdown_json", sa.JSON(), nullable=False),
        sa.Column("hard_filter_results_json", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"], ["job.id"], name=op.f("fk_job_lane_match_job_id_job"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["role_lane_id"],
            ["role_lane.id"],
            name=op.f("fk_job_lane_match_role_lane_id_role_lane"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_lane_match")),
        sa.UniqueConstraint("job_id", "role_lane_id", name=op.f("uq_job_lane_match_job_id")),
    )
    with op.batch_alter_table("job_lane_match", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_job_lane_match_job_id"), ["job_id"], unique=False)
        batch_op.create_index(
            "ix_job_lane_match_lane_score", ["role_lane_id", "score"], unique=False
        )

    op.create_table(
        "match_override",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("role_lane_id", sa.String(length=32), nullable=False),
        sa.Column("eligibility", sa.String(length=10), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"], ["job.id"], name=op.f("fk_match_override_job_id_job"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["role_lane_id"],
            ["role_lane.id"],
            name=op.f("fk_match_override_role_lane_id_role_lane"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_match_override")),
        sa.UniqueConstraint("job_id", "role_lane_id", name=op.f("uq_match_override_job_id")),
    )


def downgrade() -> None:
    op.drop_table("match_override")
    with op.batch_alter_table("job_lane_match", schema=None) as batch_op:
        batch_op.drop_index("ix_job_lane_match_lane_score")
        batch_op.drop_index(batch_op.f("ix_job_lane_match_job_id"))

    op.drop_table("job_lane_match")
