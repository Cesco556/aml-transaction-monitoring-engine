"""Tests for config loading."""

import os
import subprocess
import sys

import pytest

from aml_monitoring.config import (
    _deep_merge,
    _default_config,
    get_config,
    validate_high_risk_country,
)


def test_default_config() -> None:
    cfg = _default_config()
    assert "app" in cfg
    assert cfg["app"]["log_level"] == "INFO"
    assert "database" in cfg


def test_deep_merge() -> None:
    base = {"a": 1, "b": {"x": 1, "y": 2}}
    override = {"b": {"y": 3}, "c": 4}
    out = _deep_merge(base, override)
    assert out["a"] == 1
    assert out["b"]["x"] == 1
    assert out["b"]["y"] == 3
    assert out["c"] == 4


def test_get_config_with_file(config_path: str) -> None:
    cfg = get_config(config_path)
    assert cfg["database"]["url"] == "sqlite:///:memory:"
    assert cfg["rules"]["high_value"]["threshold_amount"] == 10000


def test_config_rejects_placeholder_xx_yy(tmp_path) -> None:
    """get_config raises ValueError when high_risk_country.countries contains XX or YY."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
app: { log_level: INFO }
database: { url: "sqlite:///:memory:" }
rules:
  high_risk_country:
    enabled: true
    countries: [IR, XX]
"""
    )
    with pytest.raises(ValueError, match="must not contain placeholder.*XX"):
        get_config(str(cfg_path))

    cfg_path.write_text(
        """
app: { log_level: INFO }
database: { url: "sqlite:///:memory:" }
rules:
  high_risk_country:
    enabled: true
    countries: [YY]
"""
    )
    with pytest.raises(ValueError, match="must not contain placeholder.*YY"):
        get_config(str(cfg_path))


def test_config_allows_valid_high_risk_countries(tmp_path) -> None:
    """get_config succeeds when high_risk_country.countries has no XX/YY."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
app: { log_level: INFO }
database: { url: "sqlite:///:memory:" }
rules:
  high_risk_country:
    enabled: true
    countries: [IR, KP, SY, CU]
"""
    )
    cfg = get_config(str(cfg_path))
    assert cfg["rules"]["high_risk_country"]["countries"] == ["IR", "KP", "SY", "CU"]


def test_validate_high_risk_country_skips_when_disabled() -> None:
    """When high_risk_country.enabled is false, XX is allowed (validation skipped)."""
    validate_high_risk_country(
        {"rules": {"high_risk_country": {"enabled": False, "countries": ["XX"]}}}
    )


def test_rules_version_respects_env() -> None:
    """AML_RULES_VERSION env is used when set (subprocess to avoid import-time cache)."""
    env = {**os.environ, "AML_RULES_VERSION": "2.0.0"}
    code = "from aml_monitoring import RULES_VERSION; assert RULES_VERSION == '2.0.0'"
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (result.stdout or "") + (result.stderr or "")
