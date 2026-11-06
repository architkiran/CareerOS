"""Bind generated document binaries to their content and approval snapshots.

Existing files remain intact and unhashed: regeneration establishes a new trusted
version rather than blessing unknown bytes during migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document", sa.Column("file_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("document") as batch_op:
        batch_op.drop_column("file_hash")
