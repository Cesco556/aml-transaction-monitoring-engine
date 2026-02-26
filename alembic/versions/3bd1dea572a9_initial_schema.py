"""initial_schema

Revision ID: 3bd1dea572a9
Revises:
Create Date: 2026-02-20 20:39:27.437028

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3bd1dea572a9"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("country", sa.String(3), nullable=False),
        sa.Column("base_risk", sa.Float(), nullable=False, server_default="10.0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("iban_or_acct", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("iban_or_acct"),
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("external_id", sa.String(64), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("merchant", sa.String(255), nullable=True),
        sa.Column("counterparty", sa.String(255), nullable=True),
        sa.Column("country", sa.String(3), nullable=True),
        sa.Column("channel", sa.String(64), nullable=True),
        sa.Column("direction", sa.String(16), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("config_hash", sa.String(64), nullable=True),
        sa.Column("rules_version", sa.String(32), nullable=True),
        sa.Column("engine_version", sa.String(32), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index("ix_transactions_external_id", "transactions", ["external_id"], unique=False)
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_fields", sa.JSON(), nullable=True),
        sa.Column("config_hash", sa.String(64), nullable=True),
        sa.Column("rules_version", sa.String(32), nullable=True),
        sa.Column("engine_version", sa.String(32), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("disposition", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_correlation_id", "alerts", ["correlation_id"], unique=False)
    op.create_table(
        "cases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="NEW"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="MEDIUM"),
        sa.Column("assigned_to", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("actor", sa.String(128), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cases_correlation_id", "cases", ["correlation_id"], unique=False)
    op.create_table(
        "case_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("alert_id", sa.Integer(), nullable=True),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"]),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "case_notes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "relationship_edges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("src_type", sa.String(32), nullable=False),
        sa.Column("src_id", sa.Integer(), nullable=False),
        sa.Column("dst_type", sa.String(32), nullable=False),
        sa.Column("dst_key", sa.String(255), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("txn_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("src_type", "src_id", "dst_type", "dst_key", name="uq_edge_src_dst"),
    )
    op.create_index(
        "ix_relationship_edges_src_type_src_id",
        "relationship_edges",
        ["src_type", "src_id"],
        unique=False,
    )
    op.create_index(
        "ix_relationship_edges_dst_key", "relationship_edges", ["dst_key"], unique=False
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=True),
        sa.Column("actor", sa.String(128), nullable=False, server_default="system"),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_correlation_id", "audit_logs", ["correlation_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_correlation_id", "audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_relationship_edges_dst_key", "relationship_edges")
    op.drop_index("ix_relationship_edges_src_type_src_id", "relationship_edges")
    op.drop_table("relationship_edges")
    op.drop_table("case_notes")
    op.drop_table("case_items")
    op.drop_index("ix_cases_correlation_id", "cases")
    op.drop_table("cases")
    op.drop_index("ix_alerts_correlation_id", "alerts")
    op.drop_table("alerts")
    op.drop_index("ix_transactions_external_id", "transactions")
    op.drop_table("transactions")
    op.drop_table("accounts")
    op.drop_table("customers")
