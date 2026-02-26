"""API tests with TestClient."""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from aml_monitoring.api import app
from aml_monitoring.audit_context import set_audit_context
from aml_monitoring.config import get_config
from aml_monitoring.db import init_db, session_scope
from aml_monitoring.models import Account, Alert, AuditLog, Customer, Transaction
from aml_monitoring.run_rules import run_rules

# For mutation tests: fixture sets AML_API_KEYS=admin:test_admin_key; use this header.
AUTH_HEADERS = {"X-API-Key": "test_admin_key"}


@pytest.fixture
def api_client(tmp_path: Path):
    """Client with DB initialized; use file DB so app lifespan shares same DB as fixture."""
    os.environ["AML_API_KEYS"] = "admin:test_admin_key"
    db_file = tmp_path / "api_test.db"
    config_file = tmp_path / "api_config.yaml"
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
  sanctions_keyword:
    enabled: true
    keywords: [sanctioned, ofac]
  high_risk_country:
    enabled: true
    countries: [IR]
scoring:
  base_risk_per_customer: 10
  max_score: 100
  thresholds: {{ low: 33, medium: 66, high: 100 }}
"""
    )
    config_path = str(config_file)
    os.environ["AML_CONFIG_PATH"] = config_path
    try:
        cfg = get_config(config_path)
        init_db(cfg["database"]["url"], echo=False)
        yield TestClient(app)
    finally:
        os.environ.pop("AML_CONFIG_PATH", None)
        os.environ.pop("AML_API_KEYS", None)


def test_score_transaction_stateless(api_client: TestClient) -> None:
    """Score a transaction without account in DB - stateless rules only."""
    resp = api_client.post(
        "/score",
        json={
            "transaction": {
                "account_id": 999,
                "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "amount": 20000,
                "currency": "USD",
                "counterparty": "Acme",
                "country": "USA",
            }
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "risk_score" in data
    assert data["band"] in ("low", "medium", "high")
    assert "rule_hits" in data
    # High value should have fired
    assert any(h["rule_id"] == "HighValueTransaction" for h in data["rule_hits"])


def test_list_alerts_empty(api_client: TestClient) -> None:
    resp = api_client.get("/alerts", params={"limit": 10})
    assert resp.status_code == 200
    assert resp.json() == []


def test_network_account_returns_edges(api_client: TestClient) -> None:
    """GET /network/account/{id} returns edges and ring_signal for seeded account."""
    from aml_monitoring.network import build_network

    config_path = os.environ.get("AML_CONFIG_PATH")
    if not config_path:
        pytest.skip("AML_CONFIG_PATH not set")
    with session_scope() as session:
        c = Customer(name="NetC", country="USA", base_risk=10.0)
        session.add(c)
        session.flush()
        a = Account(customer_id=c.id, iban_or_acct="IBAN_NET")
        session.add(a)
        session.flush()
        t = Transaction(
            account_id=a.id,
            ts=datetime.now(UTC),
            amount=100.0,
            currency="USD",
            counterparty="counterparty_a",
        )
        session.add(t)
        session.flush()
        account_id = a.id
    set_audit_context("net-build", "test")
    build_network(config_path=config_path)
    resp = api_client.get(f"/network/account/{account_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["account_id"] == account_id
    assert "edges" in data
    assert "edge_count" in data
    assert "ring_signal" in data
    assert "overlap_count" in data["ring_signal"]
    assert "linked_accounts" in data["ring_signal"]


def test_health_returns_200_and_version(api_client: TestClient) -> None:
    """GET /health returns 200 with status, engine_version, rules_version, db_status."""
    resp = api_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    assert "engine_version" in data
    assert "rules_version" in data
    assert data.get("db_status") in ("ok", "error", "unknown")


def test_openapi_includes_cases_paths(api_client: TestClient) -> None:
    """OpenAPI must expose /cases routes (prevents Docker/import regressions)."""
    resp = api_client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json().get("paths", {})
    case_paths = [p for p in paths if p.startswith("/cases")]
    assert (
        len(case_paths) >= 1
    ), f"Expected at least one path starting with /cases, got: {list(paths)}"
    assert "/cases" in paths
    assert "/cases/{case_id}" in paths


def test_alerts_filter_by_correlation_id(api_client: TestClient) -> None:
    """GET /alerts?correlation_id=X returns only alerts from runs with that correlation_id."""
    config_path = os.environ["AML_CONFIG_PATH"]
    with session_scope() as session:
        c = Customer(name="CorrCustomer", country="USA", base_risk=10.0)
        session.add(c)
        session.flush()
        a = Account(customer_id=c.id, iban_or_acct="IBAN_CORR")
        session.add(a)
        session.flush()
        t = Transaction(
            account_id=a.id,
            ts=datetime.now(UTC),
            amount=15000.0,
            currency="USD",
        )
        session.add(t)
    set_audit_context("cid-run-1", "test")
    run_rules(config_path)
    set_audit_context("cid-run-2", "test")
    run_rules(config_path)
    r1 = api_client.get("/alerts", params={"correlation_id": "cid-run-1"})
    r2 = api_client.get("/alerts", params={"correlation_id": "cid-run-2"})
    assert r1.status_code == 200 and r2.status_code == 200
    alerts1 = r1.json()
    alerts2 = r2.json()
    ids1 = {a["id"] for a in alerts1}
    ids2 = {a["id"] for a in alerts2}
    assert ids1 & ids2 == set(), "alerts must not overlap between correlation_id runs"
    for a in alerts1:
        assert a["correlation_id"] == "cid-run-1"
    for a in alerts2:
        assert a["correlation_id"] == "cid-run-2"


def test_get_transaction_404(api_client: TestClient) -> None:
    resp = api_client.get("/transactions/99999")
    assert resp.status_code == 404


def test_response_includes_x_correlation_id(api_client: TestClient) -> None:
    """API response must include X-Correlation-ID header (generated or echoed from request)."""
    resp = api_client.post(
        "/score",
        json={
            "transaction": {
                "account_id": 1,
                "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "amount": 100,
                "currency": "USD",
                "country": "USA",
            }
        },
    )
    assert resp.status_code == 200
    assert "X-Correlation-ID" in resp.headers
    assert len(resp.headers["X-Correlation-ID"]) == 36
    assert resp.headers["X-Correlation-ID"].count("-") == 4


def test_x_correlation_id_echoed_when_provided(api_client: TestClient) -> None:
    """When client sends X-Correlation-ID, response echoes the same value."""
    client_cid = "client-request-id-12345"
    resp = api_client.post(
        "/score",
        json={
            "transaction": {
                "account_id": 1,
                "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "amount": 100,
                "currency": "USD",
                "country": "USA",
            }
        },
        headers={"X-Correlation-ID": client_cid},
    )
    assert resp.status_code == 200
    assert resp.headers.get("X-Correlation-ID") == client_cid


def test_patch_alert_updates_status_and_disposition(api_client: TestClient) -> None:
    """PATCH /alerts/{id} updates status and disposition; response has X-Correlation-ID; GET reflects update."""
    with session_scope() as session:
        c = Customer(name="C", country="USA", base_risk=10.0)
        session.add(c)
        session.flush()
        a = Account(customer_id=c.id, iban_or_acct="IBANX")
        session.add(a)
        session.flush()
        t = Transaction(
            account_id=a.id,
            ts=datetime.now(UTC),
            amount=100.0,
            currency="USD",
        )
        session.add(t)
        session.flush()
        alert = Alert(
            transaction_id=t.id,
            rule_id="TestRule",
            severity="high",
            score=20.0,
            reason="Test",
        )
        session.add(alert)
        session.flush()
        alert_id = alert.id
    resp = api_client.patch(
        f"/alerts/{alert_id}",
        json={"status": "closed", "disposition": "false_positive"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "closed"
    assert data["disposition"] == "false_positive"
    assert "X-Correlation-ID" in resp.headers
    list_resp = api_client.get("/alerts", params={"limit": 10})
    assert list_resp.status_code == 200
    alerts = list_resp.json()
    found = next((x for x in alerts if x["id"] == alert_id), None)
    assert found is not None
    assert found["status"] == "closed"
    assert found["disposition"] == "false_positive"


def test_patch_alert_audit_log(api_client: TestClient) -> None:
    """After PATCH, AuditLog has disposition_update with correlation_id, actor, details_json."""
    with session_scope() as session:
        c = Customer(name="C2", country="USA", base_risk=10.0)
        session.add(c)
        session.flush()
        a = Account(customer_id=c.id, iban_or_acct="IBANY")
        session.add(a)
        session.flush()
        t = Transaction(
            account_id=a.id,
            ts=datetime.now(UTC),
            amount=200.0,
            currency="USD",
        )
        session.add(t)
        session.flush()
        alert = Alert(
            transaction_id=t.id,
            rule_id="R2",
            severity="medium",
            score=10.0,
            reason="R2",
        )
        session.add(alert)
        session.flush()
        alert_id = alert.id
    api_client.patch(
        f"/alerts/{alert_id}",
        json={"status": "closed", "disposition": "escalate"},
        headers=AUTH_HEADERS,
    )
    with session_scope() as session:
        row = session.execute(
            select(
                AuditLog.correlation_id,
                AuditLog.actor,
                AuditLog.details_json,
            )
            .where(AuditLog.action == "disposition_update")
            .order_by(AuditLog.id.desc())
            .limit(1)
        ).first()
    assert row is not None
    correlation_id, actor, details = row
    assert correlation_id is not None
    assert len(correlation_id) > 0
    assert actor == "admin"
    assert details is not None
    assert details.get("old_status") == "open"
    assert details.get("new_status") == "closed"
    assert details.get("old_disposition") is None
    assert details.get("new_disposition") == "escalate"
    assert "config_hash" in details


def test_patch_alert_404(api_client: TestClient) -> None:
    """PATCH /alerts/{id} returns 404 when alert not found."""
    resp = api_client.patch(
        "/alerts/99999",
        json={"status": "closed"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 404


def test_patch_alert_invalid_status_400(api_client: TestClient) -> None:
    """PATCH /alerts/{id} returns 400 for invalid status."""
    with session_scope() as session:
        c = Customer(name="C3", country="USA", base_risk=10.0)
        session.add(c)
        session.flush()
        a = Account(customer_id=c.id, iban_or_acct="IBANZ")
        session.add(a)
        session.flush()
        t = Transaction(
            account_id=a.id,
            ts=datetime.now(UTC),
            amount=50.0,
            currency="USD",
        )
        session.add(t)
        session.flush()
        alert = Alert(
            transaction_id=t.id,
            rule_id="R3",
            severity="low",
            score=5.0,
            reason="R3",
        )
        session.add(alert)
        session.flush()
        aid = alert.id
    resp = api_client.patch(f"/alerts/{aid}", json={"status": "invalid"}, headers=AUTH_HEADERS)
    assert resp.status_code == 400


def test_case_workflow_e2e(api_client: TestClient) -> None:
    """Create alerts, create case from alert_ids, update status, add note; verify AuditLog and GET."""
    with session_scope() as session:
        c = Customer(name="CaseCust", country="USA", base_risk=10.0)
        session.add(c)
        session.flush()
        a = Account(customer_id=c.id, iban_or_acct="IBAN_CASE")
        session.add(a)
        session.flush()
        t = Transaction(
            account_id=a.id,
            ts=datetime.now(UTC),
            amount=100.0,
            currency="USD",
        )
        session.add(t)
        session.flush()
        alert1 = Alert(
            transaction_id=t.id,
            rule_id="R1",
            severity="high",
            score=15.0,
            reason="R1",
        )
        session.add(alert1)
        session.flush()
        alert2 = Alert(
            transaction_id=t.id,
            rule_id="R2",
            severity="medium",
            score=10.0,
            reason="R2",
        )
        session.add(alert2)
        session.flush()
        a1_id, a2_id = alert1.id, alert2.id

    create_resp = api_client.post(
        "/cases",
        json={
            "alert_ids": [a1_id, a2_id],
            "priority": "HIGH",
            "assigned_to": "analyst1",
            "note": "Initial review",
        },
        headers=AUTH_HEADERS,
    )
    assert create_resp.status_code == 200
    case_data = create_resp.json()
    case_id = case_data["id"]
    assert case_data["status"] == "NEW"
    assert case_data["priority"] == "HIGH"
    assert case_data["assigned_to"] == "analyst1"
    assert len(case_data["items"]) == 2
    assert len(case_data["notes"]) == 1
    assert case_data["notes"][0]["note"] == "Initial review"
    assert case_data["correlation_id"] is not None
    assert case_data["actor"] is not None

    patch_resp = api_client.patch(
        f"/cases/{case_id}",
        json={"status": "INVESTIGATING"},
        headers=AUTH_HEADERS,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "INVESTIGATING"

    note_resp = api_client.post(
        f"/cases/{case_id}/notes",
        json={"note": "Reviewed velocity pattern; requesting more info"},
        headers=AUTH_HEADERS,
    )
    assert note_resp.status_code == 200
    assert note_resp.json()["note"] == "Reviewed velocity pattern; requesting more info"

    get_resp = api_client.get(f"/cases/{case_id}")
    assert get_resp.status_code == 200
    got = get_resp.json()
    assert got["id"] == case_id
    assert got["status"] == "INVESTIGATING"
    assert len(got["items"]) == 2
    assert len(got["notes"]) == 2

    with session_scope() as session:
        rows = list(
            session.execute(
                select(AuditLog.action, AuditLog.correlation_id, AuditLog.actor)
                .where(
                    AuditLog.entity_type == "case",
                    AuditLog.entity_id == str(case_id),
                )
                .order_by(AuditLog.id)
            ).all()
        )
    actions = [r[0] for r in rows]
    assert "case_create" in actions
    assert "case_update" in actions
    assert "case_note_add" in actions
    for r in rows:
        assert r[1] is not None  # correlation_id
        assert r[2] is not None  # actor


def test_case_invalid_status_transition_400(api_client: TestClient) -> None:
    """PATCH /cases/{id} with invalid status transition returns 400."""
    create_resp = api_client.post("/cases", json={}, headers=AUTH_HEADERS)
    assert create_resp.status_code == 200
    case_id = create_resp.json()["id"]
    resp = api_client.patch(f"/cases/{case_id}", json={"status": "CLOSED"}, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    resp2 = api_client.patch(
        f"/cases/{case_id}", json={"status": "INVESTIGATING"}, headers=AUTH_HEADERS
    )
    assert resp2.status_code == 400
    assert "Invalid transition" in resp2.json().get("detail", "")


def test_read_only_key_gets_403_on_patch_alerts(api_client: TestClient) -> None:
    """Key with scope read_only cannot PATCH /alerts (403)."""
    os.environ["AML_API_KEYS"] = "admin:test_admin_key,reader:read_only_key:read_only"
    try:
        with session_scope() as session:
            c = Customer(name="C", country="USA", base_risk=10.0)
            session.add(c)
            session.flush()
            a = Account(customer_id=c.id, iban_or_acct="IBAN_RO")
            session.add(a)
            session.flush()
            t = Transaction(
                account_id=a.id,
                ts=datetime.now(UTC),
                amount=100.0,
                currency="USD",
            )
            session.add(t)
            session.flush()
            alert = Alert(
                transaction_id=t.id,
                rule_id="R",
                severity="high",
                score=10.0,
                reason="R",
            )
            session.add(alert)
            session.flush()
            alert_id = alert.id
        resp = api_client.patch(
            f"/alerts/{alert_id}",
            json={"status": "closed"},
            headers={"X-API-Key": "read_only_key"},
        )
        assert resp.status_code == 403
        assert "scope" in resp.json().get(
            "detail", ""
        ).lower() or "Insufficient" in resp.json().get("detail", "")
    finally:
        os.environ["AML_API_KEYS"] = "admin:test_admin_key"


def test_write_key_succeeds_patch_alerts(api_client: TestClient) -> None:
    """Key with default (read_write) scope can PATCH /alerts (200)."""
    resp = api_client.patch(
        "/alerts/1",
        json={"status": "closed"},
        headers=AUTH_HEADERS,
    )
    # 404 is ok (no alert 1); 200 if alert exists
    assert resp.status_code in (200, 404)


def test_protected_endpoint_without_key_returns_401(api_client: TestClient) -> None:
    """PATCH /alerts/{id} without X-API-Key returns 401."""
    resp = api_client.patch(
        "/alerts/1",
        json={"status": "closed"},
    )
    assert resp.status_code == 401
    assert "detail" in resp.json()


def test_protected_endpoint_with_invalid_key_returns_401(api_client: TestClient) -> None:
    """PATCH /alerts/{id} with invalid X-API-Key returns 401."""
    resp = api_client.patch(
        "/alerts/1",
        json={"status": "closed"},
        headers={"X-API-Key": "invalid_key"},
    )
    assert resp.status_code == 401


def test_actor_from_api_key_not_x_actor(api_client: TestClient) -> None:
    """AuditLog actor is the authenticated identity from API key, not X-Actor header."""
    with session_scope() as session:
        c = Customer(name="SpoofC", country="USA", base_risk=10.0)
        session.add(c)
        session.flush()
        a = Account(customer_id=c.id, iban_or_acct="IBAN_SPOOF")
        session.add(a)
        session.flush()
        t = Transaction(
            account_id=a.id,
            ts=datetime.now(UTC),
            amount=100.0,
            currency="USD",
        )
        session.add(t)
        session.flush()
        alert = Alert(
            transaction_id=t.id,
            rule_id="R",
            severity="high",
            score=10.0,
            reason="R",
        )
        session.add(alert)
        session.flush()
        alert_id = alert.id
    # Valid key maps to "admin"; X-Actor spoof must be ignored
    api_client.patch(
        f"/alerts/{alert_id}",
        json={"status": "closed", "disposition": "false_positive"},
        headers={"X-API-Key": "test_admin_key", "X-Actor": "hacker"},
    )
    with session_scope() as session:
        row = session.execute(
            select(AuditLog.actor)
            .where(AuditLog.action == "disposition_update")
            .order_by(AuditLog.id.desc())
            .limit(1)
        ).first()
    assert row is not None
    assert row[0] == "admin"
