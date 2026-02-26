"""Tests for threshold tuning (train) from transaction data."""

from pathlib import Path

import pytest
import yaml

from aml_monitoring.db import init_db
from aml_monitoring.ingest import ingest_csv
from aml_monitoring.tuning import compute_tuned_config, train, write_tuned_config


@pytest.fixture
def tuning_db(tmp_path: Path) -> str:
    db_url = f"sqlite:///{tmp_path / 'tune.db'}"
    init_db(db_url, echo=False)
    return db_url


@pytest.fixture
def tuning_config(tmp_path: Path, tuning_db: str) -> str:
    cfg = {
        "database": {"url": tuning_db},
        "rules": {
            "high_value": {"enabled": True, "threshold_amount": 10000},
            "rapid_velocity": {"enabled": True, "min_transactions": 5, "window_minutes": 15},
        },
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(cfg))
    return str(path)


def test_compute_tuned_config_empty_db(tuning_config: str) -> None:
    """With no transactions, tuned fragment has rules but may rely on defaults."""
    tuned = compute_tuned_config(tuning_config)
    assert "rules" in tuned
    # Empty DB: high_value still set from logic (floor 1000)
    assert tuned["rules"].get("high_value", {}).get("threshold_amount", 0) >= 1000


def test_compute_tuned_config_with_transactions(
    tmp_path: Path, tuning_config: str, tuning_db: str
) -> None:
    """After ingest, tuned thresholds are derived from data."""
    csv_path = tmp_path / "txns.csv"
    csv_path.write_text(
        "customer_name,country,iban_or_acct,ts,amount,currency,merchant,counterparty,country_txn,channel,direction,base_risk\n"
        "A,USA,ACCT1,2025-01-01T10:00:00,500,USD,M,CP,USA,wire,out,10\n"
        "A,USA,ACCT1,2025-01-01T10:05:00,600,USD,M,CP,USA,wire,out,10\n"
        "A,USA,ACCT1,2025-01-01T10:10:00,700,USD,M,CP,USA,wire,out,10\n"
        "B,GBR,ACCT2,2025-01-01T12:00:00,100000,USD,M,CP,GBR,wire,out,10\n"
    )
    ingest_csv(str(csv_path), config_path=tuning_config)
    tuned = compute_tuned_config(tuning_config)
    assert tuned["rules"].get("high_value", {}).get("threshold_amount", 0) >= 1000
    # 99th percentile of 500,600,700,100000 is 100000 -> rounded 100000
    assert tuned["rules"]["high_value"]["threshold_amount"] == 100000


def test_train_writes_tuned_yaml(tmp_path: Path, tuning_config: str, tuning_db: str) -> None:
    """train() writes a YAML file that can be loaded."""
    csv_path = tmp_path / "txns.csv"
    csv_path.write_text(
        "customer_name,country,iban_or_acct,ts,amount,currency,merchant,counterparty,country_txn,channel,direction,base_risk\n"
        "A,USA,ACCT1,2025-01-01T10:00:00,2000,USD,M,CP,USA,wire,out,10\n"
    )
    ingest_csv(str(csv_path), config_path=tuning_config)
    out_path = tmp_path / "tuned.yaml"
    train(config_path=tuning_config, output_path=str(out_path))
    assert out_path.exists()
    loaded = yaml.safe_load(out_path.read_text())
    assert "rules" in loaded
    assert "high_value" in loaded["rules"]


def test_write_tuned_config_creates_dir(tmp_path: Path) -> None:
    """write_tuned_config creates parent dirs."""
    out = tmp_path / "sub" / "tuned.yaml"
    write_tuned_config({"rules": {"high_value": {"threshold_amount": 5000}}}, output_path=out)
    assert out.exists()
    assert "high_value" in yaml.safe_load(out.read_text()).get("rules", {})
