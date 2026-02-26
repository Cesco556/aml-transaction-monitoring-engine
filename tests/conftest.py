"""Pytest fixtures: in-memory DB, sample config."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Ensure all tests use SQLite by default; ignore DATABASE_URL unless running
# the optional Postgres smoke test (which uses POSTGRES_TEST_URL only).
if "POSTGRES_TEST_URL" not in os.environ:
    os.environ.pop("DATABASE_URL", None)

from aml_monitoring.config import get_config
from aml_monitoring.db import init_db, session_scope
from aml_monitoring.models import Account, Customer


@pytest.fixture
def config_path(tmp_path: Path) -> str:
    """Return path to a temporary config dir with default.yaml."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "default.yaml").write_text(
        """
app:
  log_level: INFO
database:
  url: "sqlite:///:memory:"
  echo: false
rules:
  high_value:
    enabled: true
    threshold_amount: 10000
  rapid_velocity:
    enabled: true
    min_transactions: 5
    window_minutes: 15
  sanctions_keyword:
    enabled: true
    keywords: [sanctioned, ofac]
  high_risk_country:
    enabled: true
    countries: [IR, KP]
scoring:
  base_risk_per_customer: 10
  max_score: 100
  thresholds: { low: 33, medium: 66, high: 100 }
"""
    )
    return str(cfg_dir / "default.yaml")


@pytest.fixture
def db_session(config_path: str):
    """Initialize DB and yield a session (caller must not commit)."""
    config = get_config(config_path)
    url = config.get("database", {}).get("url", "sqlite:///:memory:")
    init_db(url, echo=False)
    with session_scope() as session:
        yield session


@pytest.fixture
def sample_customer_and_account(db_session):
    """Create one customer and one account; return (customer_id, account_id)."""
    c = Customer(name="Test User", country="USA", base_risk=10.0)
    db_session.add(c)
    db_session.flush()
    a = Account(customer_id=c.id, iban_or_acct="US123456")
    db_session.add(a)
    db_session.flush()
    return c.id, a.id
