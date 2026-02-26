"""Determinism tests: same input → same outputs; chunk_size invariance; resume invariance."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from sqlalchemy import select

from aml_monitoring.audit_context import set_audit_context
from aml_monitoring.db import init_db, session_scope
from aml_monitoring.ingest import ingest_csv
from aml_monitoring.models import Alert, Transaction
from aml_monitoring.run_rules import run_rules


def test_same_input_twice_same_alert_set(tmp_path: Path) -> None:
    """Same CSV + config, two full runs (fresh DB each time) → same set of (external_id, rule_id)."""
    url1 = f"sqlite:///{tmp_path / 'd1.db'}"
    url2 = f"sqlite:///{tmp_path / 'd2.db'}"
    cfg = {
        "app": {"log_level": "INFO"},
        "database": {"url": url1, "echo": False},
        "rules": {
            "high_value": {"enabled": True, "threshold_amount": 10000},
            "rapid_velocity": {"enabled": False},
            "sanctions_keyword": {"enabled": True, "keywords": ["sanctioned"]},
            "high_risk_country": {"enabled": True, "countries": ["IR"]},
            "network_ring": {"enabled": False},
            "geo_mismatch": {"enabled": False},
            "structuring_smurfing": {"enabled": False},
        },
        "scoring": {
            "base_risk_per_customer": 10,
            "max_score": 100,
            "thresholds": {"low": 33, "medium": 66},
        },
    }
    csv_path = tmp_path / "data.csv"
    csv_path.write_text(
        "customer_name,country,iban_or_acct,ts,amount,currency,merchant,counterparty,country_txn,channel,direction,base_risk\n"
        "Alice,USA,IBAN1,2025-01-01T10:00:00,1000,USD,M,CP,USA,wire,out,10\n"
        "Bob,IR,IBAN2,2025-01-01T11:00:00,500,USD,M2,sanctioned,IR,wire,out,10\n"
        "Carol,USA,IBAN3,2025-01-01T12:00:00,15000,USD,M3,CP3,USA,wire,out,10\n"
    )
    config_path = tmp_path / "config.yaml"

    # Run 1
    cfg["database"]["url"] = url1
    config_path.write_text(yaml.dump(cfg))
    init_db(url1, echo=False)
    set_audit_context("run1", "test")
    ingest_csv(str(csv_path), config_path=str(config_path))
    run_rules(config_path=str(config_path))
    with session_scope() as session:
        txns1_rows = session.execute(select(Transaction.id, Transaction.external_id)).fetchall()
        txn1_id_to_ext = {r[0]: r[1] or r[0] for r in txns1_rows}
        txn1_ids = [r[0] for r in txns1_rows]
        alerts1_rows = session.execute(
            select(Alert.transaction_id, Alert.rule_id).where(Alert.transaction_id.in_(txn1_ids))
        ).fetchall()
    ext_id_to_rule1 = {ext_id: set() for ext_id in txn1_id_to_ext.values()}
    for txn_id, rule_id in alerts1_rows:
        ext_id = txn1_id_to_ext.get(txn_id, txn_id)
        if ext_id not in ext_id_to_rule1:
            ext_id_to_rule1[ext_id] = set()
        ext_id_to_rule1[ext_id].add(rule_id)
    set1 = {(eid, frozenset(rules)) for eid, rules in ext_id_to_rule1.items() if rules}

    # Run 2 (fresh DB)
    cfg["database"]["url"] = url2
    config_path.write_text(yaml.dump(cfg))
    init_db(url2, echo=False)
    set_audit_context("run2", "test")
    ingest_csv(str(csv_path), config_path=str(config_path))
    run_rules(config_path=str(config_path))
    with session_scope() as session:
        txns2_rows = session.execute(select(Transaction.id, Transaction.external_id)).fetchall()
        txn2_id_to_ext = {r[0]: r[1] or r[0] for r in txns2_rows}
        txn2_ids = [r[0] for r in txns2_rows]
        alerts2_rows = session.execute(
            select(Alert.transaction_id, Alert.rule_id).where(Alert.transaction_id.in_(txn2_ids))
        ).fetchall()
    ext_id_to_rule2 = {ext_id: set() for ext_id in txn2_id_to_ext.values()}
    for txn_id, rule_id in alerts2_rows:
        ext_id = txn2_id_to_ext.get(txn_id, txn_id)
        if ext_id not in ext_id_to_rule2:
            ext_id_to_rule2[ext_id] = set()
        ext_id_to_rule2[ext_id].add(rule_id)
    set2 = {(eid, frozenset(rules)) for eid, rules in ext_id_to_rule2.items() if rules}

    assert set1 == set2, "Same input must produce same (external_id, rule_id) set across runs"


def test_chunk_size_invariance_already_in_run_rules(tmp_path: Path) -> None:
    """Covered by test_run_rules.test_chunk_sizes_produce_identical_alerts."""
    pytest.skip("Covered by test_run_rules.test_chunk_sizes_produce_identical_alerts")
