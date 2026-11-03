"""Employer research items and evidence.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-03 11:08:24.268271
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_item",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("company_id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=True),
        sa.Column("research_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=10), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], name=op.f("fk_research_item_company_id_company")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["job.id"], name=op.f("fk_research_item_job_id_job"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_item")),
    )
    with op.batch_alter_table("research_item", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_research_item_company_id"), ["company_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_research_item_job_id"), ["job_id"], unique=False)
        batch_op.create_index("ix_research_item_status", ["status"], unique=False)

    op.create_table(
        "evidence",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("research_item_id", sa.String(length=32), nullable=True),
        sa.Column("company_id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=True),
        sa.Column("claim_type", sa.String(length=30), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.String(length=20), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("source_title", sa.String(length=300), nullable=True),
        sa.Column("source_date", sa.Date(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(), nullable=False),
        sa.Column("confidence", sa.String(length=10), nullable=False),
        sa.Column("short_excerpt", sa.Text(), nullable=True),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("reviewer_status", sa.String(length=20), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], name=op.f("fk_evidence_company_id_company")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["job.id"], name=op.f("fk_evidence_job_id_job"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["research_item_id"],
            ["research_item.id"],
            name=op.f("fk_evidence_research_item_id_research_item"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence")),
    )
    with op.batch_alter_table("evidence", schema=None) as batch_op:
        batch_op.create_index(
            "ix_evidence_company_claim", ["company_id", "claim_type"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_evidence_job_id"), ["job_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("evidence", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_evidence_job_id"))
        batch_op.drop_index("ix_evidence_company_claim")

    op.drop_table("evidence")
    with op.batch_alter_table("research_item", schema=None) as batch_op:
        batch_op.drop_index("ix_research_item_status")
        batch_op.drop_index(batch_op.f("ix_research_item_job_id"))
        batch_op.drop_index(batch_op.f("ix_research_item_company_id"))

    op.drop_table("research_item")
