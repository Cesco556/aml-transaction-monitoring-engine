"""Phase 6 Infrastructure tests: pagination, /ready, /metrics endpoints."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aml_monitoring.api import app
from aml_monitoring.config import get_config
from aml_monitoring.db import init_db, session_scope
from aml_monitoring.models import Account, Alert, Case, Customer, Transaction
from aml_monitoring.pagination import decode_cursor, encode_cursor, paginate_query
from aml_monitoring.security import reset_rate_limits

AUTH_HEADERS = {"X-API-Key": "test_admin_key"}


@pytest.fixture
def infra_client(tmp_path: Path):
    """TestClient with fresh DB for infrastructure tests."""
    reset_rate_limits()
    os.environ["AML_API_KEYS"] = "admin:test_admin_key"
    db_file = tmp_path / "infra_test.db"
    config_file = tmp_path / "infra_config.yaml"
    config_file.write_text(
        f"""
app:
  log_level: INFO
database:
  url: "sqlite:///{db_file}"
  echo: false
rules:
  high_value:
    enabled: true
    threshold_amount: 10000
  high_risk_country:
    enabled: true
    countries: [IR, KP]
scoring:
  base_risk_per_customer: 10
  max_score: 100
  thresholds: {{ low: 33, medium: 66, high: 100 }}
"""
    )
    os.environ["AML_CONFIG_PATH"] = str(config_file)
    try:
        cfg = get_config(str(config_file))
        init_db(cfg["database"]["url"], echo=False)
        yield TestClient(app)
    finally:
        os.environ.pop("AML_CONFIG_PATH", None)


# ---------------------------------------------------------------------------
# Pagination unit tests
# ---------------------------------------------------------------------------


class TestCursorEncoding:
    def test_encode_decode_roundtrip(self):
        for val in [1, 42, 999999]:
            assert decode_cursor(encode_cursor(val)) == val

    def test_decode_invalid_cursor(self):
        with pytest.raises(ValueError, match="Invalid cursor"):
            decode_cursor("not-valid-base64!!!")

    def test_encode_produces_url_safe_string(self):
        cursor = encode_cursor(12345)
        assert isinstance(cursor, str)
        # URL-safe base64 chars only
        import re

        assert re.match(r"^[A-Za-z0-9_=-]+$", cursor)


class TestPaginateQuery:
    def test_basic_pagination(self, infra_client):
        """Create alerts and paginate through them."""
        with session_scope() as session:
            c = Customer(name="PagTest", country="US", base_risk=10.0)
            session.add(c)
            session.flush()
            a = Account(customer_id=c.id, iban_or_acct="PAG001")
            session.add(a)
            session.flush()
            txn = Transaction(
                account_id=a.id, ts=datetime.now(UTC), amount=100.0, currency="USD"
            )
            session.add(txn)
            session.flush()
            for i in range(5):
                session.add(
                    Alert(
                        transaction_id=txn.id,
                        rule_id=f"TestRule{i}",
                        severity="medium",
                        score=10.0,
                        reason=f"test alert {i}",
                    )
                )
            session.flush()

        # Page 1: limit=2
        from sqlalchemy import select

        with session_scope() as session:
            stmt = select(Alert)
            items, next_cursor = paginate_query(
                stmt, session, id_column=Alert.id, cursor=None, limit=2
            )
            assert len(items) == 2
            assert next_cursor is not None

            # Page 2
            items2, next_cursor2 = paginate_query(
                stmt, session, id_column=Alert.id, cursor=next_cursor, limit=2
            )
            assert len(items2) == 2
            assert next_cursor2 is not None
            # No overlap
            ids1 = {i.id for i in items}
            ids2 = {i.id for i in items2}
            assert ids1.isdisjoint(ids2)

            # Page 3 (last item)
            items3, next_cursor3 = paginate_query(
                stmt, session, id_column=Alert.id, cursor=next_cursor2, limit=2
            )
            assert len(items3) == 1
            assert next_cursor3 is None

    def test_empty_result(self, infra_client):
        from sqlalchemy import select

        with session_scope() as session:
            stmt = select(Alert)
            items, next_cursor = paginate_query(
                stmt, session, id_column=Alert.id, cursor=None, limit=10
            )
            assert items == []
            assert next_cursor is None

    def test_limit_clamping(self, infra_client):
        """Limit < 1 gets clamped to 1, > 1000 to 1000."""
        from sqlalchemy import select

        with session_scope() as session:
            stmt = select(Alert)
            items, _ = paginate_query(
                stmt, session, id_column=Alert.id, cursor=None, limit=0
            )
            assert isinstance(items, list)


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_returns_versions(self, infra_client):
        resp = infra_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "engine_version" in data
        assert "rules_version" in data
        assert "db_status" in data

    def test_health_db_status_ok(self, infra_client):
        resp = infra_client.get("/health")
        assert resp.json()["db_status"] == "ok"


class TestReadyEndpoint:
    def test_ready_when_db_ok(self, infra_client):
        resp = infra_client.get("/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ready"] is True
        assert data["checks"]["database"] == "ok"

    def test_ready_has_ml_model_check(self, infra_client):
        resp = infra_client.get("/ready")
        data = resp.json()
        assert "ml_model" in data["checks"]


class TestMetricsEndpoint:
    def test_metrics_returns_counts(self, infra_client):
        resp = infra_client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "uptime_seconds" in data
        assert "counts" in data
        assert "transactions" in data["counts"]
        assert "alerts" in data["counts"]
        assert "cases" in data["counts"]
        assert "engine_version" in data

    def test_metrics_counts_increase(self, infra_client):
        # Get baseline
        resp1 = infra_client.get("/metrics")
        base_alerts = resp1.json()["counts"]["alerts"]

        # Add data
        with session_scope() as session:
            c = Customer(name="MetTest", country="US", base_risk=10.0)
            session.add(c)
            session.flush()
            a = Account(customer_id=c.id, iban_or_acct="MET001")
            session.add(a)
            session.flush()
            txn = Transaction(
                account_id=a.id, ts=datetime.now(UTC), amount=50.0, currency="USD"
            )
            session.add(txn)
            session.flush()
            session.add(
                Alert(
                    transaction_id=txn.id,
                    rule_id="MetricTest",
                    severity="low",
                    score=5.0,
                    reason="metric test",
                )
            )

        resp2 = infra_client.get("/metrics")
        assert resp2.json()["counts"]["alerts"] > base_alerts


class TestAlertsPagination:
    def _seed_alerts(self, n: int = 7):
        with session_scope() as session:
            c = Customer(name="PagAPI", country="US", base_risk=10.0)
            session.add(c)
            session.flush()
            a = Account(customer_id=c.id, iban_or_acct=f"APAG{n}")
            session.add(a)
            session.flush()
            txn = Transaction(
                account_id=a.id, ts=datetime.now(UTC), amount=100.0, currency="USD"
            )
            session.add(txn)
            session.flush()
            for i in range(n):
                session.add(
                    Alert(
                        transaction_id=txn.id,
                        rule_id=f"PagRule{i}",
                        severity="medium",
                        score=10.0,
                        reason=f"pag alert {i}",
                    )
                )

    def test_paginated_alerts_response_shape(self, infra_client):
        self._seed_alerts(3)
        resp = infra_client.get("/alerts", params={"limit": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "next_cursor" in data

    def test_paginated_alerts_walk(self, infra_client):
        self._seed_alerts(5)
        all_ids = []
        cursor = None
        for _ in range(10):  # safety bound
            params = {"limit": 2}
            if cursor:
                params["cursor"] = cursor
            resp = infra_client.get("/alerts", params=params)
            data = resp.json()
            all_ids.extend(a["id"] for a in data["items"])
            cursor = data["next_cursor"]
            if cursor is None:
                break
        assert len(all_ids) == 5
        assert len(set(all_ids)) == 5  # no duplicates


class TestCasesPagination:
    def test_cases_response_shape(self, infra_client):
        resp = infra_client.get("/cases", params={"limit": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "next_cursor" in data
