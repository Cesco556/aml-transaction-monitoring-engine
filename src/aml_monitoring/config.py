"""Configuration loading from YAML + environment overrides."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class AppSettings(BaseSettings):
    """App-level settings with env override."""

    model_config = SettingsConfigDict(
        env_prefix="AML_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    config_path: str = Field(default="config/default.yaml", alias="AML_CONFIG_PATH")
    log_level: str = Field(default="INFO", alias="AML_LOG_LEVEL")
    database_url: str | None = Field(default=None, alias="AML_DATABASE_URL")
    api_host: str = Field(default="0.0.0.0", alias="AML_API_HOST")
    api_port: int = Field(default=8000, alias="AML_API_PORT")


# Placeholder country codes that must be replaced before use (procurement safety).
HIGH_RISK_COUNTRY_PLACEHOLDERS = frozenset({"XX", "YY"})


def validate_high_risk_country(config: dict[str, Any]) -> None:
    """Raise ValueError if high_risk_country.countries contains placeholder XX or YY."""
    rules = config.get("rules") or {}
    hrc = rules.get("high_risk_country") or {}
    if not hrc.get("enabled", True):
        return
    countries = hrc.get("countries") or []
    for c in countries:
        code = (c if isinstance(c, str) else str(c)).strip().upper()[:3]
        if code in HIGH_RISK_COUNTRY_PLACEHOLDERS:
            raise ValueError(
                f"high_risk_country.countries must not contain placeholder {code!r}. "
                "Replace with real ISO country codes (e.g. IR, KP, SY) in config or dev/tuned override."
            )


def get_config(config_path: str | None = None) -> dict[str, Any]:
    """Load merged config from YAML and apply env overrides via AppSettings."""
    settings = AppSettings()
    path = config_path or settings.config_path
    if not Path(path).exists():
        cfg = _default_config()
        validate_high_risk_country(cfg)
        return cfg
    base = _load_yaml(path)
    config_dir = Path(path).parent
    if "default" in path or path == "config/default.yaml":
        dev_path = config_dir / "dev.yaml"
        if dev_path.exists() and os.environ.get("AML_ENV") == "dev":
            base = _deep_merge(base, _load_yaml(str(dev_path)))
    tuned_path = config_dir / "tuned.yaml"
    if tuned_path.exists():
        base = _deep_merge(base, _load_yaml(str(tuned_path)))
    # Env overrides (DATABASE_URL standard for Docker/Postgres; AML_DATABASE_URL for app)
    db_url = os.environ.get("DATABASE_URL") or settings.database_url
    if db_url:
        base.setdefault("database", {})["url"] = db_url
    if settings.log_level:
        base.setdefault("app", {})["log_level"] = settings.log_level
    validate_high_risk_country(base)
    return base


def _default_config() -> dict[str, Any]:
    return {
        "app": {"name": "aml-monitoring", "env": "default", "log_level": "INFO"},
        "database": {"url": "sqlite:///./data/aml.db", "echo": False},
        "ingest": {"csv_encoding": "utf-8", "batch_size": 500},
        "rules": {},
        "scoring": {"base_risk_per_customer": 10, "max_score": 100},
        "reporting": {"output_dir": "./reports"},
        "api": {"host": "0.0.0.0", "port": 8000},
    }


def get_config_hash(config: dict[str, Any]) -> str:
    """SHA256 of resolved config for audit reproducibility (canonical key order)."""
    canonical = yaml.dump(config, default_flow_style=False, sort_keys=True, allow_unicode=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
