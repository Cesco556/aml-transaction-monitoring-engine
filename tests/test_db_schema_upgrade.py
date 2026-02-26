"""Tests for schema upgrade gating (AML_ALLOW_SCHEMA_UPGRADE)."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from aml_monitoring.db import _missing_columns, init_db


def _create_old_schema_db(path: Path) -> None:
    """Create SQLite DB with transactions/alerts missing new columns."""
    url = f"sqlite:///{path}"
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                """
            CREATE TABLE customers (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                country VARCHAR(3) NOT NULL,
                base_risk FLOAT NOT NULL DEFAULT 10.0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """
            )
        )
        conn.execute(
            text(
                """
            CREATE TABLE accounts (
                id INTEGER NOT NULL PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                iban_or_acct VARCHAR(64) NOT NULL UNIQUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(customer_id) REFERENCES customers(id)
            )
        """
            )
        )
        conn.execute(
            text(
                """
            CREATE TABLE transactions (
                id INTEGER NOT NULL PRIMARY KEY,
                account_id INTEGER NOT NULL,
                ts DATETIME NOT NULL,
                amount FLOAT NOT NULL,
                currency VARCHAR(3) NOT NULL DEFAULT 'USD',
                merchant VARCHAR(255),
                counterparty VARCHAR(255),
                country VARCHAR(3),
                channel VARCHAR(64),
                direction VARCHAR(16),
                metadata_json JSON,
                risk_score FLOAT,
                FOREIGN KEY(account_id) REFERENCES accounts(id)
            )
        """
            )
        )
        conn.execute(
            text(
                """
            CREATE TABLE alerts (
                id INTEGER NOT NULL PRIMARY KEY,
                transaction_id INTEGER NOT NULL,
                rule_id VARCHAR(64) NOT NULL,
                severity VARCHAR(32) NOT NULL,
                score FLOAT NOT NULL,
                reason TEXT NOT NULL,
                evidence_fields JSON,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(transaction_id) REFERENCES transactions(id)
            )
        """
            )
        )
        conn.execute(
            text(
                """
            CREATE TABLE audit_logs (
                id INTEGER NOT NULL PRIMARY KEY,
                action VARCHAR(64) NOT NULL,
                entity_type VARCHAR(64) NOT NULL,
                entity_id VARCHAR(128) NOT NULL,
                ts DATETIME DEFAULT CURRENT_TIMESTAMP,
                actor VARCHAR(128) NOT NULL DEFAULT 'system',
                details_json JSON
            )
        """
            )
        )
        conn.commit()
    engine.dispose()


def test_schema_upgrade_does_not_run_without_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auto-upgrade does NOT run unless AML_ALLOW_SCHEMA_UPGRADE=true."""
    monkeypatch.delenv("AML_ALLOW_SCHEMA_UPGRADE", raising=False)
    db_path = tmp_path / "old.db"
    _create_old_schema_db(db_path)
    url = f"sqlite:///{db_path}"

    with pytest.raises(
        RuntimeError, match="Schema mismatch detected. Set AML_ALLOW_SCHEMA_UPGRADE=true"
    ):
        init_db(url, echo=False)


def test_schema_upgrade_runs_with_flag_and_adds_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With AML_ALLOW_SCHEMA_UPGRADE=true, init_db runs upgrade and columns are added."""
    db_path = tmp_path / "old.db"
    _create_old_schema_db(db_path)
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("AML_ALLOW_SCHEMA_UPGRADE", "true")

    init_db(url, echo=False)

    engine = create_engine(url)
    missing = _missing_columns(engine)
    assert missing == []
    with engine.connect() as conn:
        r = conn.execute(text("PRAGMA table_info(alerts)"))
        alert_columns = {row[1] for row in r.fetchall()}
    engine.dispose()
    assert "status" in alert_columns
    assert "disposition" in alert_columns
    assert "updated_at" in alert_columns
    assert "correlation_id" in alert_columns
