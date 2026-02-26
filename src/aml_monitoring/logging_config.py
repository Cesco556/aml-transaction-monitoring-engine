"""Structured logging setup - no secrets, PII redaction for audit."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

# Redact secrets
REDACT_FIELDS = frozenset({"password", "secret", "token", "api_key", "authorization"})
# PII: log only IDs, not identifiers or names
PII_REDACT_KEYS = frozenset(
    {
        "iban_or_acct",
        "customer_name",
        "name",
        "metadata_json",
        "counterparty",
        "merchant",
        "external_id",
        "reason",
    }
)
PII_KEY_PATTERN = re.compile(
    r"(\b" + "|".join(re.escape(k) for k in PII_REDACT_KEYS) + r")[\s=:]+[^\s,\)\]]+",
    re.IGNORECASE,
)


def _sanitize_extra(extra: dict[str, Any] | None) -> dict[str, Any]:
    if not extra:
        return {}
    out: dict[str, Any] = {}
    for k, v in extra.items():
        key_lower = k.lower()
        if any(r in key_lower for r in REDACT_FIELDS):
            out[k] = "***"
        elif any(p in key_lower for p in PII_REDACT_KEYS):
            out[k] = "[REDACTED]"
        else:
            out[k] = v
    return out


def _redact_message(msg: str) -> str:
    """Replace PII key=value or key: value in message with [REDACTED]."""
    if not isinstance(msg, str):
        return str(msg)
    return PII_KEY_PATTERN.sub(r"\1=[REDACTED]", msg)


class PIIRedactionFilter(logging.Filter):
    """Filter that redacts PII from log records (extra and message). Logs only IDs."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact_message(record.msg)
        if getattr(record, "args", None) and isinstance(record.args, tuple | dict):
            if isinstance(record.args, tuple):
                record.args = tuple(_redact_message(str(a)) for a in record.args)
            else:
                record.args = {
                    k: "[REDACTED]" if any(p in k.lower() for p in PII_REDACT_KEYS) else v
                    for k, v in record.args.items()
                }
        return True


def setup_logging(log_level: str = "INFO") -> None:
    """Configure root logger: stdout, PII redaction filter, no secrets."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        stream=sys.stdout,
        force=True,
    )
    for name in ("", "aml_monitoring"):
        log = logging.getLogger(name)
        log.addFilter(PIIRedactionFilter())
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a logger for module `name` (PII redaction applied at root)."""
    return logging.getLogger(name)
