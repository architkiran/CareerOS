"""durable agent missions and attempts

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-05 22:13:03.148087
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mission",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workflow", sa.String(length=60), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mission")),
    )
    with op.batch_alter_table("mission", schema=None) as batch_op:
        batch_op.create_index("ix_mission_created_at", ["created_at"], unique=False)
        batch_op.create_index(
            "uq_mission_active_workflow",
            ["workflow"],
            unique=True,
            sqlite_where=sa.text("status IN ('queued', 'running', 'paused')"),
        )

    op.create_table(
        "agent_run",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("mission_id", sa.String(length=32), nullable=False),
        sa.Column("agent_key", sa.String(length=40), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("task_id", sa.String(length=32), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["mission_id"], ["mission.id"], name=op.f("fk_agent_run_mission_id_mission")
        ),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], name=op.f("fk_agent_run_task_id_task")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_run")),
        sa.UniqueConstraint("mission_id", "agent_key", name=op.f("uq_agent_run_mission_id")),
        sa.UniqueConstraint("task_id", name=op.f("uq_agent_run_task_id")),
    )
    with op.batch_alter_table("agent_run", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_agent_run_mission_id"), ["mission_id"], unique=False)

    op.create_table(
        "agent_attempt",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["agent_run.id"], name=op.f("fk_agent_attempt_run_id_agent_run")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_attempt")),
        sa.UniqueConstraint("run_id", "number", name=op.f("uq_agent_attempt_run_id")),
    )
    with op.batch_alter_table("agent_attempt", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_agent_attempt_run_id"), ["run_id"], unique=False)

    op.create_table(
        "agent_dependency",
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("depends_on_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["depends_on_id"],
            ["agent_run.id"],
            name=op.f("fk_agent_dependency_depends_on_id_agent_run"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["agent_run.id"], name=op.f("fk_agent_dependency_run_id_agent_run")
        ),
        sa.PrimaryKeyConstraint("run_id", "depends_on_id", name=op.f("pk_agent_dependency")),
    )


def downgrade() -> None:
    op.drop_table("agent_dependency")
    with op.batch_alter_table("agent_attempt", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_agent_attempt_run_id"))

    op.drop_table("agent_attempt")
    with op.batch_alter_table("agent_run", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_agent_run_mission_id"))

    op.drop_table("agent_run")
    with op.batch_alter_table("mission", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_mission_active_workflow",
            sqlite_where=sa.text("status IN ('queued', 'running', 'paused')"),
        )
        batch_op.drop_index("ix_mission_created_at")

    op.drop_table("mission")
