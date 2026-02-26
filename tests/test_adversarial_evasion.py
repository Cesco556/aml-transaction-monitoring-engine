"""Adversarial tests: evasion patterns (structuring, smurfing, network ring)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import yaml
from sqlalchemy import select

from aml_monitoring.audit_context import set_audit_context
from aml_monitoring.db import init_db, session_scope
from aml_monitoring.models import Account, Customer, Transaction
from aml_monitoring.run_rules import run_rules


def _seed_structuring(tmp_path, threshold: float = 9500, min_txns: int = 3) -> str:
    """Seed account with 3 txns just below threshold in 1h → expect StructuringSmurfing."""
    url = f"sqlite:///{tmp_path / 'struct.db'}"
    cfg = {
        "app": {"log_level": "INFO"},
        "database": {"url": url, "echo": False},
        "rules": {
            "high_value": {"enabled": False},
            "rapid_velocity": {"enabled": False},
            "structuring_smurfing": {
                "enabled": True,
                "threshold_amount": threshold,
                "min_transactions": min_txns,
                "window_minutes": 60,
            },
            "sanctions_keyword": {"enabled": False},
            "high_risk_country": {"enabled": False},
            "network_ring": {"enabled": False},
            "geo_mismatch": {"enabled": False},
        },
        "scoring": {
            "base_risk_per_customer": 10,
            "max_score": 100,
            "thresholds": {"low": 33, "medium": 66},
        },
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(cfg))
    init_db(url, echo=False)
    base_ts = datetime.now(UTC) - timedelta(hours=1)
    with session_scope() as session:
        c = Customer(name="S", country="USA", base_risk=10.0)
        session.add(c)
        session.flush()
        a = Account(customer_id=c.id, iban_or_acct="IBAN_STRUCT")
        session.add(a)
        session.flush()
        for i in range(min_txns):
            t = Transaction(
                account_id=a.id,
                ts=base_ts + timedelta(minutes=i * 10),
                amount=threshold * 0.9,
                currency="USD",
            )
            session.add(t)
    set_audit_context("evasion-struct", "test")
    run_rules(config_path=str(config_path))
    return str(config_path)


def test_evasion_structuring_just_under_triggers_rule(tmp_path) -> None:
    """Struct scenario: txns just under threshold in window → StructuringSmurfing fires."""
    from aml_monitoring.models import Alert

    _seed_structuring(tmp_path)
    with session_scope() as session:
        count = (
            session.execute(select(Alert).where(Alert.rule_id == "StructuringSmurfing"))
            .scalars()
            .all()
        )
    assert len(count) >= 1, "StructuringSmurfing should fire for structuring_just_under scenario"


def test_evasion_smurfing_velocity_triggers_rule(tmp_path) -> None:
    """Smurfing scenario: many txns in short window → RapidVelocity fires."""
    from aml_monitoring.models import Alert

    url = f"sqlite:///{tmp_path / 'smurf.db'}"
    cfg = {
        "app": {"log_level": "INFO"},
        "database": {"url": url, "echo": False},
        "rules": {
            "high_value": {"enabled": False},
            "rapid_velocity": {"enabled": True, "min_transactions": 5, "window_minutes": 15},
            "structuring_smurfing": {"enabled": False},
            "sanctions_keyword": {"enabled": False},
            "high_risk_country": {"enabled": False},
            "network_ring": {"enabled": False},
            "geo_mismatch": {"enabled": False},
        },
        "scoring": {
            "base_risk_per_customer": 10,
            "max_score": 100,
            "thresholds": {"low": 33, "medium": 66},
        },
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(cfg))
    init_db(url, echo=False)
    base_ts = datetime.now(UTC)
    with session_scope() as session:
        c = Customer(name="Smurf", country="USA", base_risk=10.0)
        session.add(c)
        session.flush()
        a = Account(customer_id=c.id, iban_or_acct="IBAN_SMURF")
        session.add(a)
        session.flush()
        for i in range(6):
            t = Transaction(
                account_id=a.id,
                ts=base_ts + timedelta(minutes=i),
                amount=100.0,
                currency="USD",
            )
            session.add(t)
    set_audit_context("evasion-smurf", "test")
    run_rules(config_path=str(config_path))
    with session_scope() as session:
        count = (
            session.execute(select(Alert).where(Alert.rule_id == "RapidVelocity")).scalars().all()
        )
    assert len(count) >= 1, "RapidVelocity should fire for smurfing_velocity scenario"
