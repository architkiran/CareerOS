"""Job triage columns, task queue and pipeline runs.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-03 01:44:54.980428
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_run",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("pipeline_name", sa.String(length=100), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("counters_json", sa.JSON(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipeline_run")),
    )
    op.create_table(
        "task",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_by", sa.String(length=100), nullable=True),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task")),
    )
    with op.batch_alter_table("task", schema=None) as batch_op:
        batch_op.create_index("ix_task_status_run_after", ["status", "run_after"], unique=False)
        batch_op.create_index(
            "uq_task_active_idempotency_key",
            ["idempotency_key"],
            unique=True,
            sqlite_where=sa.text("status IN ('queued', 'running')"),
        )

    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("triage_status", sa.String(length=20), server_default="new", nullable=False)
        )
        batch_op.add_column(sa.Column("triage_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("triaged_at", sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f("ix_job_triage_status"), ["triage_status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_job_triage_status"))
        batch_op.drop_column("triaged_at")
        batch_op.drop_column("triage_reason")
        batch_op.drop_column("triage_status")

    with op.batch_alter_table("task", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_task_active_idempotency_key",
            sqlite_where=sa.text("status IN ('queued', 'running')"),
        )
        batch_op.drop_index("ix_task_status_run_after")

    op.drop_table("task")
    op.drop_table("pipeline_run")
