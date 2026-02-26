"""transactions_rule_indexes

Add indexes on transactions to speed up run-rules queries (account_id + ts, amount).

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-23

"""

from collections.abc import Sequence

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Speed up rule queries: count by account_id + time window (+ amount band)
    op.create_index(
        "ix_transactions_account_ts",
        "transactions",
        ["account_id", "ts"],
        unique=False,
    )
    op.create_index(
        "ix_transactions_account_ts_amount",
        "transactions",
        ["account_id", "ts", "amount"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_account_ts_amount", "transactions")
    op.drop_index("ix_transactions_account_ts", "transactions")
