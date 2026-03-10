"""Tests for Phase 1: Security & API Hardening.

Covers rate limiting, CORS, security headers, input validation, and OpenAPI security schemes.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aml_monitoring.api import app
from aml_monitoring.config import get_config
from aml_monitoring.db import init_db
from aml_monitoring.security import reset_rate_limits

AUTH_HEADERS = {"X-API-Key": "test_admin_key"}


@pytest.fixture
def secure_client(tmp_path: Path):
    """TestClient with security middleware active and very low rate limits for testing."""
    reset_rate_limits()
    os.environ["AML_API_KEYS"] = "admin:test_admin_key"
    db_file = tmp_path / "sec_test.db"
    config_file = tmp_path / "sec_config.yaml"
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
security:
  rate_limiting:
    enabled: true
    read_limit: "100/minute"
    write_limit: "20/minute"
  cors:
    enabled: true
    allowed_origins:
      - "http://localhost"
      - "http://localhost:8000"
      - "http://127.0.0.1"
    allow_methods: ["GET", "POST", "PATCH", "OPTIONS"]
    allow_headers: ["X-API-Key", "X-Correlation-ID", "Content-Type"]
    allow_credentials: false
  headers:
    x_content_type_options: "nosniff"
    x_frame_options: "DENY"
    x_xss_protection: "1; mode=block"
    content_security_policy: "default-src 'none'; frame-ancestors 'none'"
    referrer_policy: "strict-origin-when-cross-origin"
    cache_control: "no-store"
  request:
    max_body_size_bytes: 1048576
"""
    )
    os.environ["AML_CONFIG_PATH"] = str(config_file)
    try:
        cfg = get_config(str(config_file))
        init_db(cfg["database"]["url"], echo=False)
        yield TestClient(app)
    finally:
        os.environ.pop("AML_CONFIG_PATH", None)
        os.environ.pop("AML_API_KEYS", None)
        os.environ.pop("AML_RATE_LIMIT_READ", None)
        os.environ.pop("AML_RATE_LIMIT_WRITE", None)


@pytest.fixture
def rate_limited_client(tmp_path: Path):
    """TestClient with extremely low rate limits to trigger 429 in tests."""
    reset_rate_limits()
    os.environ["AML_API_KEYS"] = "admin:test_admin_key"
    os.environ["AML_RATE_LIMIT_READ"] = "2/minute"
    os.environ["AML_RATE_LIMIT_WRITE"] = "1/minute"
    db_file = tmp_path / "rl_test.db"
    config_file = tmp_path / "rl_config.yaml"
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
    countries: [IR]
scoring:
  base_risk_per_customer: 10
  max_score: 100
  thresholds: {{ low: 33, medium: 66, high: 100 }}
security:
  rate_limiting:
    enabled: true
    read_limit: "2/minute"
    write_limit: "1/minute"
"""
    )
    os.environ["AML_CONFIG_PATH"] = str(config_file)
    try:
        cfg = get_config(str(config_file))
        init_db(cfg["database"]["url"], echo=False)
        yield TestClient(app)
    finally:
        os.environ.pop("AML_CONFIG_PATH", None)
        os.environ.pop("AML_API_KEYS", None)
        os.environ.pop("AML_RATE_LIMIT_READ", None)
        os.environ.pop("AML_RATE_LIMIT_WRITE", None)


# ---------------------------------------------------------------------------
# Security Headers Tests
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    """Verify security headers are present on all responses."""

    def test_health_has_security_headers(self, secure_client: TestClient) -> None:
        resp = secure_client.get("/health")
        assert resp.status_code == 200
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("X-XSS-Protection") == "1; mode=block"
        assert "default-src" in resp.headers.get("Content-Security-Policy", "")
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert resp.headers.get("Cache-Control") == "no-store"

    def test_score_has_security_headers(self, secure_client: TestClient) -> None:
        resp = secure_client.post(
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
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_error_response_has_security_headers(self, secure_client: TestClient) -> None:
        """Even 404 responses should include security headers."""
        resp = secure_client.get("/transactions/99999")
        assert resp.status_code == 404
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"


# ---------------------------------------------------------------------------
# CORS Tests
# ---------------------------------------------------------------------------


class TestCORS:
    """Verify CORS headers for allowed and disallowed origins."""

    def test_cors_allowed_origin(self, secure_client: TestClient) -> None:
        """Allowed origin gets Access-Control-Allow-Origin in response."""
        resp = secure_client.get("/health", headers={"Origin": "http://localhost"})
        assert resp.headers.get("access-control-allow-origin") == "http://localhost"

    def test_cors_disallowed_origin(self, secure_client: TestClient) -> None:
        """Disallowed origin should NOT get Access-Control-Allow-Origin."""
        resp = secure_client.get("/health", headers={"Origin": "http://evil.com"})
        assert "access-control-allow-origin" not in resp.headers

    def test_cors_preflight_allowed(self, secure_client: TestClient) -> None:
        """OPTIONS preflight for allowed origin returns 200 with CORS headers."""
        resp = secure_client.options(
            "/score",
            headers={
                "Origin": "http://localhost",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-API-Key,Content-Type",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost"

    def test_cors_preflight_disallowed_origin(self, secure_client: TestClient) -> None:
        """OPTIONS preflight for disallowed origin lacks CORS headers."""
        resp = secure_client.options(
            "/score",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" not in resp.headers


# ---------------------------------------------------------------------------
# Rate Limiting Tests
# ---------------------------------------------------------------------------


class TestRateLimiting:
    """Verify rate limiting returns 429 when exceeded."""

    def test_read_rate_limit_exceeded(self, rate_limited_client: TestClient) -> None:
        """After exceeding read limit, GET /health returns 429."""
        # Limit is 2/minute; third request should be rejected
        for _ in range(2):
            resp = rate_limited_client.get("/health")
            assert resp.status_code == 200
        resp = rate_limited_client.get("/health")
        assert resp.status_code == 429
        assert "rate limit" in resp.json()["detail"].lower()

    def test_write_rate_limit_exceeded(self, rate_limited_client: TestClient) -> None:
        """After exceeding write limit, POST /score returns 429."""
        payload = {
            "transaction": {
                "account_id": 1,
                "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "amount": 100,
                "currency": "USD",
                "country": "USA",
            }
        }
        # Limit is 1/minute; second request should be rejected
        resp = rate_limited_client.post("/score", json=payload)
        assert resp.status_code == 200
        resp = rate_limited_client.post("/score", json=payload)
        assert resp.status_code == 429

    def test_429_response_format(self, rate_limited_client: TestClient) -> None:
        """429 response has proper JSON body with 'detail' key."""
        # Exhaust read limit
        for _ in range(3):
            rate_limited_client.get("/health")
        resp = rate_limited_client.get("/health")
        assert resp.status_code == 429
        data = resp.json()
        assert "detail" in data
        assert isinstance(data["detail"], str)


# ---------------------------------------------------------------------------
# Input Validation Tests
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Verify input validation and error sanitization."""

    def test_alerts_limit_upper_bound(self, secure_client: TestClient) -> None:
        """GET /alerts with limit > 1000 returns 422."""
        resp = secure_client.get("/alerts", params={"limit": 5000})
        assert resp.status_code == 422

    def test_alerts_limit_lower_bound(self, secure_client: TestClient) -> None:
        """GET /alerts with limit < 1 returns 422."""
        resp = secure_client.get("/alerts", params={"limit": 0})
        assert resp.status_code == 422

    def test_score_missing_required_fields(self, secure_client: TestClient) -> None:
        """POST /score with missing transaction returns 422."""
        resp = secure_client.post("/score", json={})
        assert resp.status_code == 422

    def test_patch_alert_invalid_json(self, secure_client: TestClient) -> None:
        """PATCH /alerts with non-JSON body returns 400 or 422."""
        resp = secure_client.patch(
            "/alerts/1",
            content=b"not json",
            headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        )
        assert resp.status_code in (400, 422)

    def test_patch_alert_empty_body_returns_400(self, secure_client: TestClient) -> None:
        """PATCH /alerts with empty JSON body returns 400."""
        resp = secure_client.patch(
            "/alerts/1",
            json={},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400
        assert "at least one" in resp.json()["detail"].lower()

    def test_error_responses_no_internal_leak(self, secure_client: TestClient) -> None:
        """Error responses should not contain stack traces or file paths."""
        resp = secure_client.get("/transactions/99999")
        body = resp.text
        assert "Traceback" not in body
        assert "/home/" not in body
        assert ".py" not in body

    def test_404_response_clean(self, secure_client: TestClient) -> None:
        """404 for missing resources gives clean message."""
        resp = secure_client.get("/transactions/99999")
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data
        assert isinstance(data["detail"], str)


# ---------------------------------------------------------------------------
# Auth Error Message Tests
# ---------------------------------------------------------------------------


class TestAuthMessages:
    """Verify improved auth error messages."""

    def test_missing_api_key_message(self, secure_client: TestClient) -> None:
        resp = secure_client.patch("/alerts/1", json={"status": "closed"})
        assert resp.status_code == 401
        assert "X-API-Key" in resp.json()["detail"]

    def test_invalid_api_key_message(self, secure_client: TestClient) -> None:
        resp = secure_client.patch(
            "/alerts/1",
            json={"status": "closed"},
            headers={"X-API-Key": "wrong_key"},
        )
        assert resp.status_code == 401
        assert "invalid" in resp.json()["detail"].lower() or "Invalid" in resp.json()["detail"]

    def test_read_only_scope_message(self, secure_client: TestClient) -> None:
        os.environ["AML_API_KEYS"] = "admin:test_admin_key,reader:ro_key:read_only"
        try:
            resp = secure_client.patch(
                "/alerts/1",
                json={"status": "closed"},
                headers={"X-API-Key": "ro_key"},
            )
            assert resp.status_code == 403
            assert "scope" in resp.json()["detail"].lower()
        finally:
            os.environ["AML_API_KEYS"] = "admin:test_admin_key"


# ---------------------------------------------------------------------------
# OpenAPI Security Scheme Tests
# ---------------------------------------------------------------------------


class TestOpenAPISecurity:
    """Verify OpenAPI spec includes security scheme definitions."""

    def test_openapi_has_security_scheme(self, secure_client: TestClient) -> None:
        resp = secure_client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        components = schema.get("components", {})
        schemes = components.get("securitySchemes", {})
        assert "ApiKeyAuth" in schemes
        assert schemes["ApiKeyAuth"]["type"] == "apiKey"
        assert schemes["ApiKeyAuth"]["in"] == "header"
        assert schemes["ApiKeyAuth"]["name"] == "X-API-Key"

    def test_openapi_has_global_security(self, secure_client: TestClient) -> None:
        resp = secure_client.get("/openapi.json")
        schema = resp.json()
        assert "security" in schema
        assert any("ApiKeyAuth" in s for s in schema["security"])

    def test_openapi_describes_endpoints(self, secure_client: TestClient) -> None:
        resp = secure_client.get("/openapi.json")
        paths = resp.json().get("paths", {})
        assert "/health" in paths
        assert "/score" in paths
        assert "/alerts" in paths


# ---------------------------------------------------------------------------
# Default Config Tests
# ---------------------------------------------------------------------------


class TestSecurityConfig:
    """Verify security-related config defaults."""

    def test_default_api_host_is_localhost(self) -> None:
        """Default config should bind to 127.0.0.1, not 0.0.0.0."""
        from aml_monitoring.config import AppSettings

        settings = AppSettings()
        assert settings.api_host == "127.0.0.1"
