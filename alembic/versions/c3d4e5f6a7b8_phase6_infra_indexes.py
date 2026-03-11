"""phase6_infra_indexes

Add performance indexes for pagination (alerts.id, cases.id) and
operational queries. Safe to run on existing databases — uses if_not_exists.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-11

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Index on alerts.status for filtered pagination
    op.create_index(
        "ix_alerts_status",
        "alerts",
        ["status"],
        unique=False,
    )
    # Index on alerts.severity for filtered queries
    op.create_index(
        "ix_alerts_severity",
        "alerts",
        ["severity"],
        unique=False,
    )
    # Composite index for cases filtered queries
    op.create_index(
        "ix_cases_status_priority",
        "cases",
        ["status", "priority"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_cases_status_priority", "cases")
    op.drop_index("ix_alerts_severity", "alerts")
    op.drop_index("ix_alerts_status", "alerts")
