"""Career OS 2.0: explainable per-job verdicts and aggregated public LCA history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "employer_lca_stat",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("normalized_name", sa.String(200), nullable=False),
        sa.Column("employer_name", sa.String(300), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("certified_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_employment", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("analyst_like", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("top_titles_json", sa.JSON(), nullable=False),
        sa.Column("states_json", sa.JSON(), nullable=False),
        sa.Column("last_decision_date", sa.String(10)),
        sa.Column("source_file", sa.String(300), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("normalized_name", "fiscal_year"),
    )
    op.create_index(
        "ix_employer_lca_stat_normalized_name", "employer_lca_stat", ["normalized_name"]
    )
    op.create_table(
        "job_verdict",
        sa.Column(
            "job_id", sa.String(32), sa.ForeignKey("job.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("verdict", sa.String(20), nullable=False),
        sa.Column("sponsorship_level", sa.String(1), nullable=False),
        sa.Column("fit", sa.String(20)),
        sa.Column("role_family", sa.String(40)),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("next_action", sa.Text(), nullable=False, server_default=""),
        sa.Column("checks_json", sa.JSON(), nullable=False),
        sa.Column("sponsorship_json", sa.JSON(), nullable=False),
        sa.Column("fit_json", sa.JSON(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("engine_version", sa.String(20), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_verdict_verdict", "job_verdict", ["verdict"])


def downgrade() -> None:
    op.drop_table("job_verdict")
    op.drop_table("employer_lca_stat")
