"""private interview practice plans and answers

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-06 07:17:30.160889
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_plan",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], name=op.f("fk_interview_plan_job_id_job")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview_plan")),
        sa.UniqueConstraint("input_hash", name=op.f("uq_interview_plan_input_hash")),
    )
    with op.batch_alter_table("interview_plan", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_interview_plan_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_interview_plan_job_id"), ["job_id"], unique=False)

    op.create_table(
        "interview_answer",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("plan_id", sa.String(length=32), nullable=False),
        sa.Column("question_id", sa.String(length=40), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("reflection", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["interview_plan.id"],
            name=op.f("fk_interview_answer_plan_id_interview_plan"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview_answer")),
        sa.UniqueConstraint("plan_id", "question_id", name=op.f("uq_interview_answer_plan_id")),
    )
    with op.batch_alter_table("interview_answer", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_interview_answer_plan_id"), ["plan_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("interview_answer", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_interview_answer_plan_id"))

    op.drop_table("interview_answer")
    with op.batch_alter_table("interview_plan", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_interview_plan_job_id"))
        batch_op.drop_index(batch_op.f("ix_interview_plan_created_at"))

    op.drop_table("interview_plan")
