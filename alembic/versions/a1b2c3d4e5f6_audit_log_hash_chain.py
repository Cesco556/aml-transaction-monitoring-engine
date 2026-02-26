"""audit_log_hash_chain

Revision ID: a1b2c3d4e5f6
Revises: 3bd1dea572a9
Create Date: 2026-02-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "3bd1dea572a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("prev_hash", sa.String(64), nullable=True))
    op.add_column("audit_logs", sa.Column("row_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_logs", "row_hash")
    op.drop_column("audit_logs", "prev_hash")
