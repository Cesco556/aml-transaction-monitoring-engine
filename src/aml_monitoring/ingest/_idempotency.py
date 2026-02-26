"""Deterministic external_id for idempotent ingestion."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal


def _ts_utc_iso(ts: datetime) -> str:
    """Canonical UTC ISO string (naive treated as UTC)."""
    ts = ts.astimezone(UTC) if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
    return ts.isoformat()


def compute_external_id(
    account_id: int,
    ts: datetime,
    amount: float,
    currency: str,
    counterparty: str | None,
    direction: str | None,
) -> str:
    """
    SHA256 of canonical (account_id, ts_utc_iso, amount_2dp, currency_upper,
    counterparty_lower, direction_lower). Stable across whitespace/casing.
    """
    ts_str = _ts_utc_iso(ts)
    amount_canon = str(Decimal(str(amount)).quantize(Decimal("0.01")))
    currency_canon = (currency or "").strip().upper()
    counterparty_canon = (counterparty or "").strip().lower()
    direction_canon = (direction or "").strip().lower()
    parts = (
        str(account_id),
        ts_str,
        amount_canon,
        currency_canon,
        counterparty_canon,
        direction_canon,
    )
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def external_id_for_row(
    external_id_override: str | None,
    account_id: int,
    ts: datetime,
    amount: float,
    currency: str,
    counterparty: str | None,
    direction: str | None,
) -> str:
    """
    Use source-provided id (e.g. transaction_id UUID) when present,
    else compute_external_id. Source id must be <= 64 chars for DB.
    """
    if external_id_override:
        s = external_id_override.strip()
        if s and len(s) <= 64:
            return s
    return compute_external_id(account_id, ts, amount, currency, counterparty, direction)
