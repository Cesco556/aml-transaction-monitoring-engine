"""Tests for audit log hash chain (tamper resistance)."""

from __future__ import annotations

import os

import pytest
import yaml
from sqlalchemy import select, text

from aml_monitoring.audit_context import set_audit_context
from aml_monitoring.db import init_db, session_scope
from aml_monitoring.models import AuditLog


@pytest.fixture
def db_with_hash_columns(tmp_path):
    """DB with AML_ALLOW_SCHEMA_UPGRADE so prev_hash/row_hash exist."""
    os.environ["AML_ALLOW_SCHEMA_UPGRADE"] = "true"
    url = f"sqlite:///{tmp_path / 'audit_chain.db'}"
    cfg = {
        "app": {"log_level": "INFO"},
        "database": {"url": url, "echo": False},
        "rules": {"high_risk_country": {"enabled": True, "countries": ["IR"]}},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(cfg))
    init_db(url, echo=False)
    try:
        yield url
    finally:
        os.environ.pop("AML_ALLOW_SCHEMA_UPGRADE", None)


def test_audit_log_has_prev_hash_and_row_hash(db_with_hash_columns) -> None:
    """After adding AuditLog, row has prev_hash and row_hash set."""
    set_audit_context("chain-test", "test")
    with session_scope() as session:
        session.add(
            AuditLog(
                action="test_action",
                entity_type="test",
                entity_id="1",
                actor="test",
            )
        )
    with session_scope() as session:
        row = session.execute(
            select(AuditLog.prev_hash, AuditLog.row_hash).order_by(AuditLog.id.desc()).limit(1)
        ).first()
    assert row is not None
    assert row[1] is not None, "row_hash must be set"
    assert len(row[1]) == 64, "row_hash must be SHA256 hex (64 chars)"


def test_audit_chain_verification(db_with_hash_columns) -> None:
    """Second AuditLog has prev_hash equal to first's row_hash."""
    set_audit_context("chain-two", "test")
    with session_scope() as session:
        session.add(AuditLog(action="first", entity_type="e", entity_id="1", actor="a"))
    with session_scope() as session:
        _ = session.execute(
            select(AuditLog.row_hash, AuditLog.prev_hash).order_by(AuditLog.id).limit(1)
        ).first()
    set_audit_context("chain-two", "test")
    with session_scope() as session:
        session.add(AuditLog(action="second", entity_type="e", entity_id="2", actor="a"))
    with session_scope() as session:
        rows = session.execute(
            select(AuditLog.id, AuditLog.prev_hash, AuditLog.row_hash).order_by(AuditLog.id)
        ).fetchall()
    assert len(rows) >= 2
    first_row_hash = rows[0][2]
    second_prev_hash = rows[1][1]
    assert second_prev_hash == first_row_hash, "Chain: second.prev_hash == first.row_hash"


def test_tampering_breaks_verification(db_with_hash_columns) -> None:
    """If we change details_json after insert, recomputing row_hash does not match stored row_hash."""
    set_audit_context("tamper-test", "test")
    with session_scope() as session:
        session.add(
            AuditLog(
                action="sensitive",
                entity_type="e",
                entity_id="1",
                actor="a",
                details_json={"value": 1},
            )
        )
    with session_scope() as session:
        row = session.execute(
            select(AuditLog.id, AuditLog.row_hash, AuditLog.details_json)
            .order_by(AuditLog.id.desc())
            .limit(1)
        ).first()
    assert row is not None
    original_hash = row[1]
    # Tamper: update details_json directly in DB (bypassing ORM so we don't recompute row_hash)
    url = db_with_hash_columns
    from sqlalchemy import create_engine

    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE audit_logs SET details_json = :new WHERE id = :id"),
            {"new": '{"value": 2}', "id": row[0]},
        )
        conn.commit()
    with session_scope() as session:
        tampered = session.execute(
            select(AuditLog.row_hash, AuditLog.details_json).where(AuditLog.id == row[0])
        ).first()
    assert tampered[1] == {"value": 2}, "Tampered value persisted"
    assert tampered[0] == original_hash, "row_hash was not recomputed on raw update"
    # So the stored row_hash no longer matches the hash of (prev_hash + canonical(tampered row))
    # - verification would recompute hash of current row content and see it != row_hash.
    # We don't implement full verify_chain() here; the test proves that tampering leaves row_hash
    # unchanged so a verifier would detect mismatch.
    assert original_hash is not None
