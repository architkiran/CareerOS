"""Switch off two remote boards that produced no eligible or researchable role.

Measured on 2026-11-11: Remotive 13 postings and We Work Remotely 163, every one rejected
or needing review. The rows and history stay; re-enable either on the Sources page.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE source SET enabled = 0 WHERE source_type IN ('remotive', 'wwr')")


def downgrade() -> None:
    op.execute("UPDATE source SET enabled = 1 WHERE source_type IN ('remotive', 'wwr')")
