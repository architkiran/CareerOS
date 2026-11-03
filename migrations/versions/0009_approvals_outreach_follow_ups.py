"""Approvals, outreach contacts and drafts, follow-ups.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-03 11:17:26.407817
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approval",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("action_type", sa.String(length=30), nullable=False),
        sa.Column("target_type", sa.String(length=30), nullable=False),
        sa.Column("target_id", sa.String(length=32), nullable=False),
        sa.Column("destination", sa.String(length=1000), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_snapshot_path", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(length=30), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval")),
    )
    with op.batch_alter_table("approval", schema=None) as batch_op:
        batch_op.create_index("ix_approval_status", ["status"], unique=False)
        batch_op.create_index("ix_approval_target", ["target_type", "target_id"], unique=False)

    op.create_table(
        "outreach_contact",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("company_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=200), nullable=True),
        sa.Column("public_profile_url", sa.String(length=1000), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], name=op.f("fk_outreach_contact_company_id_company")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outreach_contact")),
    )
    with op.batch_alter_table("outreach_contact", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_outreach_contact_company_id"), ["company_id"], unique=False
        )

    op.create_table(
        "follow_up",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("application_id", sa.String(length=32), nullable=False),
        sa.Column("contact_id", sa.String(length=32), nullable=True),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("action_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["application.id"],
            name=op.f("fk_follow_up_application_id_application"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["outreach_contact.id"],
            name=op.f("fk_follow_up_contact_id_outreach_contact"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_follow_up")),
    )
    with op.batch_alter_table("follow_up", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_follow_up_application_id"), ["application_id"], unique=False
        )
        batch_op.create_index("ix_follow_up_status_due", ["status", "due_at"], unique=False)

    op.create_table(
        "outreach_draft",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("contact_id", sa.String(length=32), nullable=False),
        sa.Column("application_id", sa.String(length=32), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("recipient", sa.String(length=300), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=True),
        sa.Column("body_path", sa.String(length=500), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["application.id"],
            name=op.f("fk_outreach_draft_application_id_application"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["outreach_contact.id"],
            name=op.f("fk_outreach_draft_contact_id_outreach_contact"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outreach_draft")),
    )
    with op.batch_alter_table("outreach_draft", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_outreach_draft_application_id"), ["application_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_outreach_draft_contact_id"), ["contact_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("outreach_draft", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_outreach_draft_contact_id"))
        batch_op.drop_index(batch_op.f("ix_outreach_draft_application_id"))

    op.drop_table("outreach_draft")
    with op.batch_alter_table("follow_up", schema=None) as batch_op:
        batch_op.drop_index("ix_follow_up_status_due")
        batch_op.drop_index(batch_op.f("ix_follow_up_application_id"))

    op.drop_table("follow_up")
    with op.batch_alter_table("outreach_contact", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_outreach_contact_company_id"))

    op.drop_table("outreach_contact")
    with op.batch_alter_table("approval", schema=None) as batch_op:
        batch_op.drop_index("ix_approval_target")
        batch_op.drop_index("ix_approval_status")

    op.drop_table("approval")
