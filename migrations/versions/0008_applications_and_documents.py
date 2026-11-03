"""Applications, documents, claim maps and application events.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-03 11:12:28.430386
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "application",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("role_lane_id", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("next_follow_up_at", sa.DateTime(), nullable=True),
        sa.Column("outcome", sa.String(length=30), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], name=op.f("fk_application_job_id_job")),
        sa.ForeignKeyConstraint(
            ["role_lane_id"],
            ["role_lane.id"],
            name=op.f("fk_application_role_lane_id_role_lane"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application")),
        sa.UniqueConstraint("job_id", name=op.f("uq_application_job_id")),
    )
    with op.batch_alter_table("application", schema=None) as batch_op:
        batch_op.create_index(
            "ix_application_next_follow_up_at", ["next_follow_up_at"], unique=False
        )
        batch_op.create_index("ix_application_status", ["status"], unique=False)

    op.create_table(
        "application_event",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("application_id", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["application.id"],
            name=op.f("fk_application_event_application_id_application"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_event")),
    )
    with op.batch_alter_table("application_event", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_application_event_application_id"), ["application_id"], unique=False
        )

    op.create_table(
        "document",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("application_id", sa.String(length=32), nullable=False),
        sa.Column("document_type", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("base_template_id", sa.String(length=100), nullable=False),
        sa.Column("model_provider", sa.String(length=30), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("qa_json", sa.JSON(), nullable=False),
        sa.Column("warnings_acknowledged_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["application.id"],
            name=op.f("fk_document_application_id_application"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document")),
        sa.UniqueConstraint(
            "application_id", "document_type", "version", name=op.f("uq_document_application_id")
        ),
    )
    with op.batch_alter_table("document", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_document_application_id"), ["application_id"], unique=False
        )

    op.create_table(
        "document_claim",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("document_id", sa.String(length=32), nullable=False),
        sa.Column("section", sa.String(length=30), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("supporting_profile_fact_ids_json", sa.JSON(), nullable=False),
        sa.Column("verification_status", sa.String(length=20), nullable=False),
        sa.Column("warning", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            name=op.f("fk_document_claim_document_id_document"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_claim")),
    )
    with op.batch_alter_table("document_claim", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_document_claim_document_id"), ["document_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("document_claim", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_document_claim_document_id"))

    op.drop_table("document_claim")
    with op.batch_alter_table("document", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_document_application_id"))

    op.drop_table("document")
    with op.batch_alter_table("application_event", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_application_event_application_id"))

    op.drop_table("application_event")
    with op.batch_alter_table("application", schema=None) as batch_op:
        batch_op.drop_index("ix_application_status")
        batch_op.drop_index("ix_application_next_follow_up_at")

    op.drop_table("application")
