"""Tests for ML anomaly detection layer (Phase 3)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aml_monitoring.config import get_config
from aml_monitoring.db import init_db, session_scope
from aml_monitoring.models import Account, Customer, Transaction
from aml_monitoring.rules.base import RuleContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ml_config_path(tmp_path: Path) -> str:
    """Config that enables ML anomaly detection with a temp model path."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    model_path = str(tmp_path / "models" / "test_model.joblib")
    (cfg_dir / "default.yaml").write_text(
        f"""
app:
  log_level: INFO
database:
  url: "sqlite:///:memory:"
  echo: false
rules:
  high_value:
    enabled: false
  rapid_velocity:
    enabled: false
  sanctions_keyword:
    enabled: false
  high_risk_country:
    enabled: false
  geo_mismatch:
    enabled: false
  structuring_smurfing:
    enabled: false
  network_ring:
    enabled: false
ml:
  anomaly_detection:
    enabled: true
    model_path: "{model_path}"
    contamination: 0.1
    n_estimators: 50
    threshold: 0.7
    features:
      - amount_zscore
      - velocity_1h
      - velocity_24h
      - counterparty_diversity
      - country_diversity
      - time_of_day_sin
      - time_of_day_cos
"""
    )
    return str(cfg_dir / "default.yaml")


@pytest.fixture
def ml_db_session(ml_config_path: str):
    """Initialize DB and yield session with ML config."""
    config = get_config(ml_config_path)
    url = config["database"]["url"]
    init_db(url, echo=False)
    with session_scope() as session:
        yield session


@pytest.fixture
def seeded_session(ml_db_session):
    """Session with a customer, account, and 20 transactions."""
    session = ml_db_session
    c = Customer(name="ML Test User", country="USA", base_risk=10.0)
    session.add(c)
    session.flush()
    a = Account(customer_id=c.id, iban_or_acct="ML_ACCT_001")
    session.add(a)
    session.flush()

    base_time = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
    for i in range(20):
        # Mix normal and potentially anomalous amounts
        amount = 500.0 + (i * 100) if i < 18 else 50000.0
        txn = Transaction(
            account_id=a.id,
            ts=base_time + timedelta(hours=i),
            amount=amount,
            currency="USD",
            counterparty=f"CP_{i % 5}",
            country=["US", "GB", "DE"][i % 3],
            channel="online",
            direction="out",
        )
        session.add(txn)
    session.flush()
    return session, c.id, a.id


# ---------------------------------------------------------------------------
# Feature extraction tests
# ---------------------------------------------------------------------------

class TestFeatureExtraction:
    def test_build_feature_matrix(self, seeded_session):
        from aml_monitoring.ml.features import build_feature_matrix

        session, _, _ = seeded_session
        df = build_feature_matrix(session)

        assert len(df) == 20
        expected_cols = {
            "amount_zscore", "velocity_1h", "velocity_24h",
            "counterparty_diversity", "country_diversity",
            "time_of_day_sin", "time_of_day_cos",
        }
        assert expected_cols.issubset(set(df.columns))
        assert df.index.name == "transaction_id"

    def test_build_feature_matrix_empty(self, ml_db_session):
        from aml_monitoring.ml.features import build_feature_matrix

        df = build_feature_matrix(ml_db_session)
        assert df.empty

    def test_extract_single_features(self, seeded_session):
        from aml_monitoring.ml.features import extract_single_features

        session, cust_id, acct_id = seeded_session
        from sqlalchemy import select
        from aml_monitoring.models import Transaction as Txn

        txn = session.execute(select(Txn).limit(1)).scalar_one()

        ctx = RuleContext(
            transaction_id=txn.id,
            account_id=txn.account_id,
            customer_id=cust_id,
            ts=txn.ts,
            amount=txn.amount,
            currency=txn.currency,
            merchant=txn.merchant,
            counterparty=txn.counterparty,
            country=txn.country,
            channel=txn.channel,
            direction=txn.direction,
            session=session,
        )

        features = extract_single_features(ctx, session)
        assert "amount_zscore" in features
        assert "velocity_1h" in features
        assert "time_of_day_sin" in features
        # Cyclical encoding: sin^2 + cos^2 ≈ 1
        assert abs(features["time_of_day_sin"] ** 2 + features["time_of_day_cos"] ** 2 - 1.0) < 0.01

    def test_feature_values_sensible(self, seeded_session):
        from aml_monitoring.ml.features import build_feature_matrix

        session, _, _ = seeded_session
        df = build_feature_matrix(session)

        # Last two transactions have amount 50000 — should have high z-score
        last_two = df.iloc[-2:]
        assert all(last_two["amount_zscore"] > 1.0)


# ---------------------------------------------------------------------------
# Model training and scoring
# ---------------------------------------------------------------------------

class TestAnomalyModel:
    def test_train_and_save(self, seeded_session, ml_config_path):
        from aml_monitoring.ml.anomaly import train_anomaly_model

        session, _, _ = seeded_session
        config = get_config(ml_config_path)
        ml_cfg = config["ml"]["anomaly_detection"]

        result = train_anomaly_model(session, ml_cfg)
        assert result["sample_count"] == 20
        assert result["feature_count"] == 7
        assert 0.0 <= result["anomaly_ratio"] <= 1.0
        assert Path(result["model_path"]).exists()

    def test_load_model(self, seeded_session, ml_config_path):
        from aml_monitoring.ml.anomaly import load_model, train_anomaly_model

        session, _, _ = seeded_session
        config = get_config(ml_config_path)
        ml_cfg = config["ml"]["anomaly_detection"]

        train_anomaly_model(session, ml_cfg)
        artifact = load_model(ml_cfg["model_path"])
        assert artifact is not None
        assert "model" in artifact
        assert "feature_names" in artifact
        assert "data_hash" in artifact

    def test_load_model_missing(self):
        from aml_monitoring.ml.anomaly import load_model

        assert load_model("/nonexistent/path/model.joblib") is None

    def test_score_anomaly(self, seeded_session, ml_config_path):
        from aml_monitoring.ml.anomaly import load_model, score_anomaly, train_anomaly_model

        session, _, _ = seeded_session
        config = get_config(ml_config_path)
        ml_cfg = config["ml"]["anomaly_detection"]

        train_anomaly_model(session, ml_cfg)
        artifact = load_model(ml_cfg["model_path"])

        # Normal transaction features
        normal_features = {
            "amount_zscore": 0.0,
            "velocity_1h": 1.0,
            "velocity_24h": 5.0,
            "counterparty_diversity": 3.0,
            "country_diversity": 2.0,
            "time_of_day_sin": 0.5,
            "time_of_day_cos": 0.866,
        }
        score = score_anomaly(normal_features, artifact)
        assert 0.0 <= score <= 1.0

    def test_anomalous_scores_higher(self, seeded_session, ml_config_path):
        from aml_monitoring.ml.anomaly import load_model, score_anomaly, train_anomaly_model

        session, _, _ = seeded_session
        config = get_config(ml_config_path)
        ml_cfg = config["ml"]["anomaly_detection"]

        train_anomaly_model(session, ml_cfg)
        artifact = load_model(ml_cfg["model_path"])

        normal = {
            "amount_zscore": 0.0,
            "velocity_1h": 1.0,
            "velocity_24h": 5.0,
            "counterparty_diversity": 3.0,
            "country_diversity": 2.0,
            "time_of_day_sin": 0.5,
            "time_of_day_cos": 0.866,
        }
        extreme = {
            "amount_zscore": 15.0,
            "velocity_1h": 50.0,
            "velocity_24h": 200.0,
            "counterparty_diversity": 50.0,
            "country_diversity": 20.0,
            "time_of_day_sin": -0.9,
            "time_of_day_cos": -0.4,
        }
        normal_score = score_anomaly(normal, artifact)
        extreme_score = score_anomaly(extreme, artifact)
        # Extreme features should score higher (more anomalous)
        assert extreme_score > normal_score

    def test_train_empty_db_raises(self, ml_db_session, ml_config_path):
        from aml_monitoring.ml.anomaly import train_anomaly_model

        config = get_config(ml_config_path)
        ml_cfg = config["ml"]["anomaly_detection"]

        with pytest.raises(ValueError, match="No transactions"):
            train_anomaly_model(ml_db_session, ml_cfg)


# ---------------------------------------------------------------------------
# MLAnomalyRule tests
# ---------------------------------------------------------------------------

class TestMLAnomalyRule:
    def test_rule_with_trained_model(self, seeded_session, ml_config_path):
        from aml_monitoring.ml.anomaly import train_anomaly_model
        from aml_monitoring.rules.ml_anomaly import MLAnomalyRule

        session, cust_id, acct_id = seeded_session
        config = get_config(ml_config_path)
        ml_cfg = config["ml"]["anomaly_detection"]

        train_anomaly_model(session, ml_cfg)

        rule = MLAnomalyRule(ml_cfg)

        # Use last transaction (high amount — likely anomalous)
        from sqlalchemy import select
        from aml_monitoring.models import Transaction as Txn

        txn = session.execute(select(Txn).order_by(Txn.id.desc()).limit(1)).scalar_one()

        ctx = RuleContext(
            transaction_id=txn.id,
            account_id=txn.account_id,
            customer_id=cust_id,
            ts=txn.ts,
            amount=txn.amount,
            currency=txn.currency,
            merchant=txn.merchant,
            counterparty=txn.counterparty,
            country=txn.country,
            channel=txn.channel,
            direction=txn.direction,
            session=session,
        )

        results = rule.evaluate(ctx)
        # May or may not trigger depending on threshold; just verify no crash
        # and that results are valid RuleResult instances
        for r in results:
            assert r.rule_id == "MLAnomaly"
            assert r.evidence_fields is not None
            assert "anomaly_score" in r.evidence_fields

    def test_rule_without_model_graceful(self, ml_db_session, ml_config_path):
        """Rule should return empty list when no model exists."""
        from aml_monitoring.rules.ml_anomaly import MLAnomalyRule

        config = get_config(ml_config_path)
        ml_cfg = config["ml"]["anomaly_detection"]
        ml_cfg["model_path"] = "/nonexistent/model.joblib"

        rule = MLAnomalyRule(ml_cfg)

        # Seed minimal data for context
        c = Customer(name="Test", country="US", base_risk=10.0)
        ml_db_session.add(c)
        ml_db_session.flush()
        a = Account(customer_id=c.id, iban_or_acct="NOMODEL001")
        ml_db_session.add(a)
        ml_db_session.flush()
        txn = Transaction(
            account_id=a.id,
            ts=datetime(2026, 1, 1, tzinfo=UTC),
            amount=1000.0,
            currency="USD",
        )
        ml_db_session.add(txn)
        ml_db_session.flush()

        ctx = RuleContext(
            transaction_id=txn.id,
            account_id=a.id,
            customer_id=c.id,
            ts=txn.ts,
            amount=txn.amount,
            currency=txn.currency,
            merchant=None,
            counterparty=None,
            country=None,
            channel=None,
            direction=None,
            session=ml_db_session,
        )

        results = rule.evaluate(ctx)
        assert results == []

    def test_rule_registered_in_get_all_rules(self, ml_config_path):
        """MLAnomalyRule should appear when ml.anomaly_detection.enabled=true."""
        from aml_monitoring.rules import get_all_rules

        config = get_config(ml_config_path)
        rules = get_all_rules(config)
        rule_ids = [r.rule_id for r in rules]
        assert "MLAnomaly" in rule_ids

    def test_rule_not_registered_when_disabled(self, tmp_path):
        """MLAnomalyRule should NOT appear when ml.anomaly_detection.enabled=false."""
        from aml_monitoring.rules import get_all_rules

        cfg_dir = tmp_path / "config2"
        cfg_dir.mkdir()
        (cfg_dir / "default.yaml").write_text(
            """
app:
  log_level: INFO
database:
  url: "sqlite:///:memory:"
rules:
  high_value:
    enabled: false
  rapid_velocity:
    enabled: false
  sanctions_keyword:
    enabled: false
  high_risk_country:
    enabled: false
  geo_mismatch:
    enabled: false
  structuring_smurfing:
    enabled: false
  network_ring:
    enabled: false
ml:
  anomaly_detection:
    enabled: false
"""
        )
        config = get_config(str(cfg_dir / "default.yaml"))
        rules = get_all_rules(config)
        rule_ids = [r.rule_id for r in rules]
        assert "MLAnomaly" not in rule_ids


# ---------------------------------------------------------------------------
# ML module availability
# ---------------------------------------------------------------------------

class TestMLModule:
    def test_ml_available(self):
        from aml_monitoring.ml import ML_AVAILABLE
        assert ML_AVAILABLE is True

    def test_model_versioning(self, seeded_session, ml_config_path):
        """Training twice with same data should produce same data_hash."""
        from aml_monitoring.ml.anomaly import train_anomaly_model

        session, _, _ = seeded_session
        config = get_config(ml_config_path)
        ml_cfg = config["ml"]["anomaly_detection"]

        r1 = train_anomaly_model(session, ml_cfg)
        r2 = train_anomaly_model(session, ml_cfg)
        assert r1["data_hash"] == r2["data_hash"]
