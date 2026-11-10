"""Source timestamps, presence, and append-only normalized revision history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("job", "job_source_record"):
        op.add_column(
            table,
            sa.Column("publication_kind", sa.String(20), nullable=False, server_default="unknown"),
        )
        op.add_column(table, sa.Column("last_modified_at", sa.DateTime(timezone=True)))
        op.add_column(table, sa.Column("fetched_at", sa.DateTime(timezone=True)))
    op.add_column("job", sa.Column("material_updated_at", sa.DateTime(timezone=True)))
    op.add_column("job_source_record", sa.Column("published_at", sa.DateTime(timezone=True)))
    op.add_column("job_source_record", sa.Column("is_listed", sa.Boolean()))
    # Old last_seen already records a successful fetch; do not invent publication or presence.
    op.execute("UPDATE job SET fetched_at = last_seen_at")
    op.execute("UPDATE job_source_record SET fetched_at = last_seen_at")
    op.create_index("ix_job_posted_at", "job", ["posted_at"])
    op.create_table(
        "job_revision",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "job_id", sa.String(32), sa.ForeignKey("job.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "source_id",
            sa.String(32),
            sa.ForeignKey("source.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("change_type", sa.String(30), nullable=False),
        sa.Column("previous_json", sa.JSON(), nullable=False),
        sa.Column("current_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_job_revision_job_id", "job_revision", ["job_id"])


def downgrade() -> None:
    op.drop_table("job_revision")
    op.drop_index("ix_job_posted_at", table_name="job")
    for table, cols in (
        ("job", ("publication_kind", "last_modified_at", "fetched_at", "material_updated_at")),
        (
            "job_source_record",
            ("publication_kind", "last_modified_at", "fetched_at", "published_at", "is_listed"),
        ),
    ):
        with op.batch_alter_table(table) as batch:
            for col in cols:
                batch.drop_column(col)
