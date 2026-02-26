"""Tests for ingest reject visibility: bad rows are counted and reasons persisted in audit."""

from pathlib import Path

import pytest
import yaml
from sqlalchemy import select

from aml_monitoring.audit_context import set_audit_context
from aml_monitoring.db import init_db, session_scope
from aml_monitoring.ingest import ingest_csv, ingest_jsonl
from aml_monitoring.models import AuditLog


@pytest.fixture
def config_with_db(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'reject_test.db'}"
    cfg = {
        "app": {"log_level": "INFO"},
        "database": {"url": url, "echo": False},
        "rules": {},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(cfg))
    init_db(url, echo=False)
    return str(config_path)


def test_csv_ingest_rejects_missing_iban_audit_has_reject_reasons(
    config_with_db: str, tmp_path: Path
) -> None:
    """Rows with missing iban_or_acct are rejected and reasons persisted in ingest audit."""
    csv_path = tmp_path / "dirty.csv"
    csv_path.write_text(
        """customer_name,country,iban_or_acct,ts,amount,currency,merchant,counterparty,country_txn,channel,direction,base_risk
Alice,USA,IBAN001,2025-01-01T10:00:00,1000,USD,M,CP,USA,wire,out,10
Bob,GBR,,2025-01-01T11:00:00,500,USD,M2,CP2,GBR,wire,out,10
Carol,FRA,,2025-01-01T12:00:00,600,USD,M3,CP3,FRA,wire,out,10
Dave,DEU,IBAN002,2025-01-01T13:00:00,700,USD,M4,CP4,DEU,wire,out,10
"""
    )
    set_audit_context("reject-test-csv", "test-actor")
    read, inserted = ingest_csv(str(csv_path), config_path=config_with_db)
    assert read == 4
    assert inserted == 2  # only rows with iban

    with session_scope() as session:
        row = session.execute(
            select(AuditLog.details_json)
            .where(AuditLog.action == "ingest")
            .where(AuditLog.entity_id == str(csv_path))
            .order_by(AuditLog.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    assert row is not None
    details = row if isinstance(row, dict) else row[0]
    assert details["rows_read"] == 4
    assert details["rows_inserted"] == 2
    assert details["rows_rejected"] == 2
    assert "reject_reasons" in details
    reasons = details["reject_reasons"]
    assert len(reasons) == 2
    assert all(r == "missing_iban" for r in reasons)


def test_csv_ingest_rejects_parse_error_audit_has_reject_reasons(
    config_with_db: str, tmp_path: Path
) -> None:
    """Rows with invalid ts or amount are rejected and parse_error reason persisted."""
    csv_path = tmp_path / "bad_parse.csv"
    csv_path.write_text(
        """customer_name,country,iban_or_acct,ts,amount,currency,merchant,counterparty,country_txn,channel,direction,base_risk
Alice,USA,IBAN001,2025-01-01T10:00:00,1000,USD,M,CP,USA,wire,out,10
Bob,GBR,IBAN002,not-a-date,500,USD,M2,CP2,GBR,wire,out,10
Carol,FRA,IBAN003,2025-01-01T12:00:00,not-a-number,USD,M3,CP3,FRA,wire,out,10
"""
    )
    set_audit_context("reject-parse-csv", "test-actor")
    read, inserted = ingest_csv(str(csv_path), config_path=config_with_db)
    assert read == 3
    assert inserted == 1

    with session_scope() as session:
        row = session.execute(
            select(AuditLog.details_json)
            .where(AuditLog.action == "ingest")
            .order_by(AuditLog.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    assert row is not None
    details = row if isinstance(row, dict) else row[0]
    assert details["rows_rejected"] == 2
    assert "reject_reasons" in details
    assert any("parse_error" in r for r in details["reject_reasons"])


def test_csv_ingest_no_rejects_when_all_valid_audit_has_no_reject_keys(
    config_with_db: str, tmp_path: Path
) -> None:
    """When no rows are rejected, details_json does not include rows_rejected or reject_reasons."""
    csv_path = tmp_path / "all_valid.csv"
    csv_path.write_text(
        """customer_name,country,iban_or_acct,ts,amount,currency,merchant,counterparty,country_txn,channel,direction,base_risk
Alice,USA,IBAN001,2025-01-01T10:00:00,1000,USD,M,CP,USA,wire,out,10
"""
    )
    set_audit_context("no-reject-csv", "test-actor")
    read, inserted = ingest_csv(str(csv_path), config_path=config_with_db)
    assert read == 1 and inserted == 1

    with session_scope() as session:
        row = session.execute(
            select(AuditLog.details_json)
            .where(AuditLog.action == "ingest")
            .order_by(AuditLog.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    assert row is not None
    details = row if isinstance(row, dict) else row[0]
    assert details["rows_read"] == 1
    assert details["rows_inserted"] == 1
    assert "rows_rejected" not in details
    assert "reject_reasons" not in details


def test_jsonl_ingest_rejects_audit_has_reject_reasons(config_with_db: str, tmp_path: Path) -> None:
    """JSONL: missing iban and parse errors produce rows_rejected and reject_reasons in audit."""
    jsonl_path = tmp_path / "dirty.jsonl"
    jsonl_path.write_text(
        '{"customer_name":"A","country":"USA","iban_or_acct":"IB1","ts":"2025-01-01T10:00:00","amount":100,"currency":"USD"}\n'
        "{}\n"
        '{"customer_name":"B","country":"GBR","iban_or_acct":"","ts":"2025-01-01T11:00:00","amount":200,"currency":"USD"}\n'
    )
    set_audit_context("reject-jsonl", "test-actor")
    read, inserted = ingest_jsonl(str(jsonl_path), config_path=config_with_db)
    assert read == 3
    assert inserted == 1

    with session_scope() as session:
        row = session.execute(
            select(AuditLog.details_json)
            .where(AuditLog.action == "ingest")
            .where(AuditLog.entity_id == str(jsonl_path))
            .order_by(AuditLog.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    assert row is not None
    details = row if isinstance(row, dict) else row[0]
    assert details["rows_rejected"] == 2
    assert "reject_reasons" in details
    assert len(details["reject_reasons"]) == 2
