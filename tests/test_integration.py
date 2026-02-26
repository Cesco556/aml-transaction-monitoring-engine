"""Integration tests: DB, ingest, run_rules, report, idempotency, audit."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from sqlalchemy import func, select

from aml_monitoring.audit_context import set_audit_context
from aml_monitoring.config import get_config, get_config_hash
from aml_monitoring.db import init_db, session_scope
from aml_monitoring.ingest import ingest_csv
from aml_monitoring.models import Account, Alert, AuditLog, Customer, Transaction
from aml_monitoring.network import build_network
from aml_monitoring.reporting import generate_sar_report
from aml_monitoring.reproduce import reproduce_run
from aml_monitoring.run_rules import run_rules


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    p = tmp_path / "sample.csv"
    p.write_text(
        """customer_name,country,iban_or_acct,ts,amount,currency,merchant,counterparty,country_txn,channel,direction,base_risk
Alice,USA,IBAN001,2025-01-01T10:00:00,1000,USD,Merchant A,CP A,USA,wire,out,10
Bob,GBR,IBAN002,2025-01-01T11:00:00,15000,USD,Merchant B,CP B,GBR,wire,out,10
"""
    )
    return p


@pytest.fixture
def integration_config(tmp_path: Path) -> str:
    """Config file that uses a file-based SQLite DB in tmp_path."""
    db_path = tmp_path / "test.db"
    url = f"sqlite:///{db_path}"
    cfg = {
        "app": {"log_level": "INFO"},
        "database": {"url": url, "echo": False},
        "rules": {
            "high_value": {"enabled": True, "threshold_amount": 10000},
            "rapid_velocity": {"enabled": True, "min_transactions": 5, "window_minutes": 15},
            "sanctions_keyword": {"enabled": True, "keywords": ["sanctioned"]},
            "high_risk_country": {"enabled": True, "countries": ["IR"]},
        },
        "scoring": {
            "base_risk_per_customer": 10,
            "max_score": 100,
            "thresholds": {"low": 33, "medium": 66, "high": 100},
        },
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(cfg))
    init_db(url, echo=False)
    return str(config_path)


def test_ingest_csv_then_run_rules(sample_csv: Path, integration_config: str) -> None:
    """Ingest CSV, run rules with same config (same DB), expect alerts for high-value."""
    cfg = get_config(integration_config)
    init_db(cfg["database"]["url"], echo=False)
    read, inserted = ingest_csv(str(sample_csv), batch_size=10, config_path=integration_config)
    assert read == 2
    assert inserted == 2

    processed, alerts = run_rules(integration_config)
    assert processed == 2
    assert alerts >= 1


def test_reingest_same_file_twice_no_new_rows(sample_csv: Path, integration_config: str) -> None:
    """Re-ingest same file twice: second run inserts 0 new rows."""
    cfg = get_config(integration_config)
    init_db(cfg["database"]["url"], echo=False)
    read1, inserted1 = ingest_csv(str(sample_csv), batch_size=10, config_path=integration_config)
    assert read1 == 2 and inserted1 == 2

    with session_scope() as session:
        count_after_first = session.execute(select(func.count(Transaction.id))).scalar_one()
    read2, inserted2 = ingest_csv(str(sample_csv), batch_size=10, config_path=integration_config)
    assert read2 == 2 and inserted2 == 0

    with session_scope() as session:
        count_after_second = session.execute(select(func.count(Transaction.id))).scalar_one()
    assert count_after_second == count_after_first


def test_reingest_different_whitespace_casing_same_external_id(
    integration_config: str, tmp_path: Path
) -> None:
    """Same logical row with different whitespace/casing produces same external_id -> no new rows."""
    cfg = get_config(integration_config)
    init_db(cfg["database"]["url"], echo=False)
    csv1 = tmp_path / "a.csv"
    csv1.write_text(
        """customer_name,country,iban_or_acct,ts,amount,currency,merchant,counterparty,country_txn,channel,direction,base_risk
Alice,USA,IBAN001,2025-01-01T10:00:00,1000.10,  usd  ,M,  CP A  ,USA,wire,  OUT  ,10
"""
    )
    csv2 = tmp_path / "b.csv"
    csv2.write_text(
        """customer_name,country,iban_or_acct,ts,amount,currency,merchant,counterparty,country_txn,channel,direction,base_risk
Alice,USA,IBAN001,2025-01-01T10:00:00,1000.1,USD,M,cp a,USA,wire,out,10
"""
    )
    read1, inserted1 = ingest_csv(str(csv1), config_path=integration_config)
    assert read1 == 1 and inserted1 == 1
    with session_scope() as session:
        ext_id = (
            session.execute(
                select(Transaction.external_id).where(Transaction.external_id.isnot(None)).limit(1)
            )
            .scalars()
            .first()
        )
    read2, inserted2 = ingest_csv(str(csv2), config_path=integration_config)
    assert read2 == 1 and inserted2 == 0
    with session_scope() as session:
        count = session.execute(select(func.count(Transaction.id))).scalar_one()
        ext_id2 = (
            session.execute(
                select(Transaction.external_id).where(Transaction.external_id.isnot(None)).limit(1)
            )
            .scalars()
            .first()
        )
    assert count == 1
    assert ext_id == ext_id2


def test_alerts_include_config_hash_and_versions(integration_config: str, sample_csv: Path) -> None:
    """After run_rules, alerts have config_hash, rules_version, engine_version."""
    cfg = get_config(integration_config)
    init_db(cfg["database"]["url"], echo=False)
    ingest_csv(str(sample_csv), config_path=integration_config)
    run_rules(integration_config)

    with session_scope() as session:
        rows = session.execute(
            select(Alert.config_hash, Alert.rules_version, Alert.engine_version).where(
                Alert.config_hash.isnot(None)
            )
        ).fetchall()
    assert len(rows) >= 1
    config_hash = get_config_hash(cfg)
    for config_hash_val, rules_ver, engine_ver in rows:
        assert config_hash_val == config_hash
        assert rules_ver is not None
        assert engine_ver is not None


def test_alerts_include_per_rule_hash_in_evidence(
    integration_config: str, sample_csv: Path
) -> None:
    """After run_rules, each alert evidence_fields contains rule_hash (stable per rule_id)."""
    cfg = get_config(integration_config)
    init_db(cfg["database"]["url"], echo=False)
    ingest_csv(str(sample_csv), config_path=integration_config)
    run_rules(integration_config)

    with session_scope() as session:
        rows = session.execute(
            select(Alert.rule_id, Alert.evidence_fields).where(Alert.evidence_fields.isnot(None))
        ).fetchall()
    assert len(rows) >= 1
    for rule_id, evidence in rows:
        assert evidence is not None
        assert "rule_hash" in evidence, f"Alert for rule {rule_id} must have rule_hash in evidence"
        assert isinstance(evidence["rule_hash"], str) and len(evidence["rule_hash"]) > 0


def test_audit_logs_created_for_each_stage(
    integration_config: str, sample_csv: Path, tmp_path: Path
) -> None:
    """Audit logs exist for ingest, run_rules, generate_report with counts, config_hash, correlation_id, actor."""
    cfg = get_config(integration_config)
    init_db(cfg["database"]["url"], echo=False)
    set_audit_context("test-correlation-123", "integration-test")
    ingest_csv(str(sample_csv), config_path=integration_config)
    run_rules(integration_config)
    with session_scope() as session:
        generate_sar_report(session, str(tmp_path / "reports"), config_path=integration_config)

    with session_scope() as session:
        log_rows = session.execute(
            select(
                AuditLog.action,
                AuditLog.correlation_id,
                AuditLog.actor,
                AuditLog.details_json,
            ).order_by(AuditLog.id)
        ).fetchall()
    actions = {r[0] for r in log_rows}
    assert "ingest" in actions
    assert "run_rules" in actions
    assert "generate_report" in actions

    config_hash = get_config_hash(cfg)
    for row in log_rows:
        action, correlation_id, actor, details_json = row
        assert correlation_id is not None, f"AuditLog action={action} must have correlation_id"
        assert actor is not None, f"AuditLog action={action} must have actor"
        assert correlation_id == "test-correlation-123"
        assert actor == "integration-test"
        assert details_json is not None
        assert details_json.get("config_hash") == config_hash
        if action == "ingest":
            assert "rows_read" in details_json and "rows_inserted" in details_json
            assert "duration_seconds" in details_json
        if action == "run_rules":
            assert "processed" in details_json and "alerts_created" in details_json
            assert "duration_seconds" in details_json
        if action == "generate_report":
            assert "alert_count" in details_json and "duration_seconds" in details_json


def test_report_generation(integration_config: str, tmp_path: Path) -> None:
    """Generate report after adding an alert manually."""
    cfg = get_config(integration_config)
    init_db(cfg["database"]["url"], echo=False)
    with session_scope() as session:
        c = Customer(name="R", country="USA", base_risk=10)
        session.add(c)
        session.flush()
        a = Account(customer_id=c.id, iban_or_acct="X")
        session.add(a)
        session.flush()
        t = Transaction(
            account_id=a.id,
            ts=datetime.now(UTC),
            amount=100,
            currency="USD",
        )
        session.add(t)
        session.flush()
        alert = Alert(
            transaction_id=t.id, rule_id="TestRule", severity="high", score=20, reason="Test"
        )
        session.add(alert)
    out_dir = tmp_path / "reports"
    set_audit_context("report-test-corr", "test-actor")
    with session_scope() as session:
        jp, cp = generate_sar_report(
            session, str(out_dir), include_evidence=False, config_path=integration_config
        )
    assert Path(jp).exists()
    assert Path(cp).exists()
    with session_scope() as session:
        row = session.execute(
            select(AuditLog.correlation_id, AuditLog.actor)
            .where(AuditLog.action == "generate_report")
            .order_by(AuditLog.id.desc())
            .limit(1)
        ).first()
    assert row is not None
    assert row[0] == "report-test-corr"
    assert row[1] == "test-actor"


def test_sar_report_includes_timeliness_and_hours_to_disposition(
    integration_config: str, tmp_path: Path
) -> None:
    """SAR report JSON includes created_at, updated_at, hours_to_disposition; computed correctly."""
    cfg = get_config(integration_config)
    init_db(cfg["database"]["url"], echo=False)
    with session_scope() as session:
        c = Customer(name="T", country="USA", base_risk=10)
        session.add(c)
        session.flush()
        a = Account(customer_id=c.id, iban_or_acct="ACCT_TIMELINESS")
        session.add(a)
        session.flush()
        t = Transaction(
            account_id=a.id,
            ts=datetime.now(UTC),
            amount=100,
            currency="USD",
        )
        session.add(t)
        session.flush()
        created = datetime.now(UTC) - timedelta(hours=2)
        updated = datetime.now(UTC)
        alert = Alert(
            transaction_id=t.id,
            rule_id="TimelinessRule",
            severity="high",
            score=20,
            reason="Test",
            created_at=created,
            updated_at=updated,
        )
        session.add(alert)
    out_dir = tmp_path / "reports"
    set_audit_context("timeliness-corr", "test")
    with session_scope() as session:
        jp, _ = generate_sar_report(
            session, str(out_dir), include_evidence=False, config_path=integration_config
        )
    with open(jp, encoding="utf-8") as f:
        data = json.load(f)
    assert "alerts" in data and len(data["alerts"]) >= 1
    rec = next(r for r in data["alerts"] if r.get("rule_id") == "TimelinessRule")
    assert "created_at" in rec
    assert "updated_at" in rec
    assert "hours_to_disposition" in rec
    assert rec["hours_to_disposition"] is not None
    assert 1.99 <= rec["hours_to_disposition"] <= 2.01


def test_network_ring_indicator_integration(tmp_path: Path) -> None:
    """Build network from two accounts sharing counterparties; run rules; assert NetworkRingIndicator alert and audit."""
    db_path = tmp_path / "network_test.db"
    url = f"sqlite:///{db_path}"
    cfg = {
        "app": {"log_level": "INFO"},
        "database": {"url": url, "echo": False},
        "rules": {
            "high_value": {"enabled": False},
            "rapid_velocity": {"enabled": False},
            "sanctions_keyword": {"enabled": False},
            "high_risk_country": {"enabled": False},
            "network_ring": {
                "enabled": True,
                "min_shared_counterparties": 2,
                "min_linked_accounts": 2,
                "lookback_days": 30,
                "severity": "high",
                "score_delta": 40,
            },
        },
        "scoring": {
            "base_risk_per_customer": 10,
            "max_score": 100,
            "thresholds": {"low": 33, "medium": 66, "high": 100},
        },
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(cfg))
    init_db(url, echo=False)

    with session_scope() as session:
        c1 = Customer(name="C1", country="USA", base_risk=10.0)
        session.add(c1)
        session.flush()
        c2 = Customer(name="C2", country="USA", base_risk=10.0)
        session.add(c2)
        session.flush()
        a1 = Account(customer_id=c1.id, iban_or_acct="IBAN_N1")
        session.add(a1)
        session.flush()
        a2 = Account(customer_id=c2.id, iban_or_acct="IBAN_N2")
        session.add(a2)
        session.flush()
        a3 = Account(customer_id=c1.id, iban_or_acct="IBAN_N3")
        session.add(a3)
        session.flush()
        now = datetime.now(UTC)
        for acc, cp_list in [
            (a1.id, ["shared_cp_a", "shared_cp_b"]),
            (a2.id, ["shared_cp_a", "shared_cp_b"]),
            (a3.id, ["shared_cp_a", "shared_cp_b"]),
        ]:
            for cp in cp_list:
                t = Transaction(
                    account_id=acc,
                    ts=now,
                    amount=100.0,
                    currency="USD",
                    counterparty=cp,
                )
                session.add(t)

    set_audit_context("network-test-corr", "integration-test")
    result = build_network(config_path=str(config_path))
    assert result["edge_count"] >= 1

    processed, alerts_created = run_rules(str(config_path))
    assert processed >= 6

    with session_scope() as session:
        ring_rows = list(
            session.execute(
                select(Alert.severity, Alert.evidence_fields).where(
                    Alert.rule_id == "NetworkRingIndicator"
                )
            ).all()
        )
    assert len(ring_rows) >= 1
    severity, evidence_fields = ring_rows[0]
    assert severity == "high"
    assert evidence_fields is not None
    assert "linked_accounts" in evidence_fields
    assert "shared_counterparties" in evidence_fields
    assert "overlap_count" in evidence_fields
    assert "degree" in evidence_fields
    assert "lookback_days" in evidence_fields

    with session_scope() as session:
        log_row = session.execute(
            select(AuditLog.action, AuditLog.correlation_id, AuditLog.actor)
            .where(AuditLog.action == "network_build")
            .order_by(AuditLog.id.desc())
            .limit(1)
        ).first()
    assert log_row is not None
    assert log_row[0] == "network_build"
    assert log_row[1] == "network-test-corr"
    assert log_row[2] == "integration-test"


def test_reproduce_run_produces_bundle_and_audit_log(
    integration_config: str, sample_csv: Path, tmp_path: Path
) -> None:
    """Run pipeline with known correlation_id; reproduce-run; assert bundle and reproduce_run AuditLog."""
    import json

    cfg = get_config(integration_config)
    init_db(cfg["database"]["url"], echo=False)
    cid = "repro-test-correlation-id-12345"
    set_audit_context(cid, "integration-test")
    ingest_csv(str(sample_csv), batch_size=10, config_path=integration_config)
    processed, alerts_created = run_rules(integration_config)
    assert processed >= 2
    assert alerts_created >= 1

    out_file = tmp_path / "repro_bundle.json"
    path = reproduce_run(cid, out_path=str(out_file), config_path=integration_config)
    assert Path(path).exists()

    with open(path, encoding="utf-8") as f:
        bundle = json.load(f)
    assert bundle["metadata"]["correlation_id"] == cid
    assert "audit_logs" in bundle
    assert "alerts" in bundle
    assert "cases" in bundle
    assert "network" in bundle
    assert "transactions" in bundle
    assert "config" in bundle and "resolved" in bundle["config"]
    assert len(bundle["audit_logs"]) >= 1
    assert len(bundle["alerts"]) >= 1
    assert isinstance(bundle["transactions"], list)
    alert_txn_ids = {a["transaction_id"] for a in bundle["alerts"]}
    txn_ids_in_bundle = {t["id"] for t in bundle["transactions"]}
    assert (
        alert_txn_ids <= txn_ids_in_bundle
    ), "Every alert transaction_id must exist in transactions"
    for t in bundle["transactions"]:
        for key in ("id", "account_id", "ts", "amount", "currency"):
            assert key in t, f"Transaction must have key {key}"
    assert bundle["config"]["resolved"] is not None
    assert "rules" in bundle["config"]["resolved"]

    with session_scope() as session:
        row = session.execute(
            select(AuditLog.action, AuditLog.entity_id, AuditLog.details_json)
            .where(AuditLog.action == "reproduce_run")
            .order_by(AuditLog.id.desc())
            .limit(1)
        ).first()
    assert row is not None
    assert row[0] == "reproduce_run"
    assert row[1] == cid
    assert row[2] is not None
    assert row[2].get("target_correlation_id") == cid
    assert "output_path" in row[2]
