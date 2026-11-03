"""Companies, sources, source runs, jobs and job source records.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-03 01:37:27.772730
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "company",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("canonical_name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("domain", sa.String(length=200), nullable=True),
        sa.Column("careers_url", sa.String(length=500), nullable=True),
        sa.Column("company_notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company")),
        sa.UniqueConstraint("normalized_name", name=op.f("uq_company_normalized_name")),
    )
    op.create_table(
        "job",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("canonical_url", sa.String(length=1000), nullable=False),
        sa.Column("company_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("normalized_title", sa.String(length=300), nullable=False),
        sa.Column("location_text", sa.String(length=500), nullable=True),
        sa.Column("workplace_type", sa.String(length=20), nullable=True),
        sa.Column("employment_type", sa.String(length=20), nullable=True),
        sa.Column("department", sa.String(length=200), nullable=True),
        sa.Column("description_text", sa.Text(), nullable=False),
        sa.Column("description_hash", sa.String(length=64), nullable=False),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("salary_max", sa.Integer(), nullable=True),
        sa.Column("salary_currency", sa.String(length=10), nullable=True),
        sa.Column("salary_interval", sa.String(length=20), nullable=True),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("possible_duplicate_of_id", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], name=op.f("fk_job_company_id_company")
        ),
        sa.ForeignKeyConstraint(
            ["possible_duplicate_of_id"],
            ["job.id"],
            name=op.f("fk_job_possible_duplicate_of_id_job"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job")),
    )
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.create_index("ix_job_canonical_url", ["canonical_url"], unique=False)
        batch_op.create_index("ix_job_company_id", ["company_id"], unique=False)
        batch_op.create_index("ix_job_dedupe_key", ["dedupe_key"], unique=False)
        batch_op.create_index("ix_job_first_seen_at", ["first_seen_at"], unique=False)
        batch_op.create_index("ix_job_status", ["status"], unique=False)
        batch_op.create_index("ix_job_title", ["title"], unique=False)

    op.create_table(
        "source",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("board_token", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("company_id", sa.String(length=32), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("rate_limit_seconds", sa.Double(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], name=op.f("fk_source_company_id_company")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source")),
        sa.UniqueConstraint("source_type", "board_token", name=op.f("uq_source_source_type")),
    )
    op.create_table(
        "job_source_record",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("raw_hash", sa.String(length=64), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"], ["job.id"], name=op.f("fk_job_source_record_job_id_job"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name=op.f("fk_job_source_record_source_id_source"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_source_record")),
        sa.UniqueConstraint(
            "source_id", "external_id", name=op.f("uq_job_source_record_source_id")
        ),
    )
    with op.batch_alter_table("job_source_record", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_job_source_record_job_id"), ["job_id"], unique=False)

    op.create_table(
        "source_run",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("fetched_count", sa.Integer(), nullable=False),
        sa.Column("new_count", sa.Integer(), nullable=False),
        sa.Column("updated_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("invalid_count", sa.Integer(), nullable=False),
        sa.Column("closed_count", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name=op.f("fk_source_run_source_id_source"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_run")),
    )
    with op.batch_alter_table("source_run", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_source_run_source_id"), ["source_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("source_run", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_source_run_source_id"))

    op.drop_table("source_run")
    with op.batch_alter_table("job_source_record", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_job_source_record_job_id"))

    op.drop_table("job_source_record")
    op.drop_table("source")
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_index("ix_job_title")
        batch_op.drop_index("ix_job_status")
        batch_op.drop_index("ix_job_first_seen_at")
        batch_op.drop_index("ix_job_dedupe_key")
        batch_op.drop_index("ix_job_company_id")
        batch_op.drop_index("ix_job_canonical_url")

    op.drop_table("job")
    op.drop_table("company")
