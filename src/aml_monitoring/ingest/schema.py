"""
Schema adaptation: map external column names to canonical transaction fields.
Allows the engine to ingest data without requiring fixed column names.
The engine can learn from the data by inferring a column map from headers
and optionally persisting it next to the file (e.g. transactions.schema.json)
so future ingests reuse the same mapping without code changes.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_FILENAME_SUFFIX = ".schema.json"

# Canonical field names used by the engine (DB + rules).
REQUIRED_CANONICAL = frozenset({"iban_or_acct", "ts", "amount"})
OPTIONAL_CANONICAL = frozenset(
    {
        "customer_name",
        "country",
        "currency",
        "merchant",
        "counterparty",
        "country_txn",
        "channel",
        "direction",
        "base_risk",
    }
)
ALL_CANONICAL = REQUIRED_CANONICAL | OPTIONAL_CANONICAL

# Optional: if present in row, use as external_id for idempotency (e.g. UUID).
EXTERNAL_ID_SOURCE_ALIASES = frozenset(
    {
        "transaction_id",
        "id",
        "txn_id",
        "transaction_uuid",
        "external_id",
        "txn_ref",
        "txnref",
        "ref",
    }
)

# For each canonical field, possible external header names (normalized: lower, spaces/underscores).
# First match wins when inferring column map.
ALIASES: dict[str, list[str]] = {
    "iban_or_acct": [
        "iban_or_acct",
        "iban",
        "account_id",
        "account_number",
        "acct_id",
        "account",
        "acc_id",
        "acct_no",
        "acctno",
        "account_no",
    ],
    "ts": [
        "ts",
        "timestamp",
        "date",
        "value_date",
        "booking_date",
        "transaction_date",
        "created_at",
        "event_timestamp",
        "event_date",
        "event_time",
        "settlement_date",
        "settlementdate",
        "eventdate",
        "eventtime",
    ],
    "amount": [
        "amount",
        "transaction_amount",
        "value",
        "amt",
        "sum",
        "total",
        "amount_minor_units",
        "amount_minor",
        "minor_units",
        "amountminorunits",
    ],
    "currency": [
        "currency",
        "currency_code",
        "ccy",
        "curr",
        "currency_iso",
        "ccy_alpha",
        "ccyalpha",
    ],
    "customer_name": [
        "customer_name",
        "customer",
        "name",
        "account_holder",
        "holder_name",
        "acct_holder",
        "accountholder",
        "acctholder",
    ],
    "country": [
        "country",
        "origin_country",
        "customer_country",
        "home_country",
        "country_code",
        "residence_country",
        "geo_origin",
        "geoorigin",
    ],
    "country_txn": [
        "country_txn",
        "destination_country",
        "merchant_country",
        "counterparty_country",
        "txn_country",
        "geo_destination",
        "geodestination",
    ],
    "merchant": [
        "merchant",
        "merchant_name",
        "merchant_name",
        "payee",
        "beneficiary_name",
        "merchant_id",
        "narrative",
    ],
    "counterparty": [
        "counterparty",
        "counterparty_name",
        "counterparty_id",
        "counter_party",
        "beneficiary",
        "payer",
        "beneficiary_name",
        "beneficiary_ref",
        "remitter_ref",
        "beneficiaryname",
        "beneficiaryref",
        "remitterref",
    ],
    "channel": [
        "channel",
        "channel_type",
        "channel_name",
        "entry_channel",
        "entry_code",
        "device_type",
        "auth_method",
    ],
    "direction": [
        "direction",
        "debit_credit",
        "flow",
        "dr_cr",
        "type_direction",
    ],
    "base_risk": [
        "base_risk",
        "risk_band",
        "risk_score",
        "risk_level",
        "customer_risk",
        "risk_tier",
        "risktier",
    ],
}


def _normalize_header(h: str) -> str:
    """Lowercase, collapse spaces/underscores/dots to single underscore."""
    if not h:
        return ""
    s = re.sub(r"[\s._-]+", "_", str(h).strip().lower())
    return re.sub(r"_+", "_", s).strip("_")


def infer_column_map(
    headers: list[str],
    config_map: dict[str, str] | None = None,
) -> dict[str, str]:
    """
    Build external_column -> canonical_field from headers (and optional config override).
    config_map takes precedence: keys are external names (as in file), values are canonical names.
    """
    if config_map:
        # Normalize config keys to match how we'll look up (original casing from file).
        return dict(config_map)

    normalized_to_original: dict[str, str] = {}
    for h in headers:
        if not h:
            continue
        norm = _normalize_header(h)
        if norm and norm not in normalized_to_original:
            normalized_to_original[norm] = h

    result: dict[str, str] = {}
    for canonical, alias_list in ALIASES.items():
        for alias in alias_list:
            anorm = _normalize_header(alias)
            if anorm in normalized_to_original:
                external_name = normalized_to_original[anorm]
                if external_name not in result:
                    result[external_name] = canonical
                break
    return result


def _parse_ts(s: str | datetime | int | float) -> datetime:
    if isinstance(s, datetime):
        return s
    if isinstance(s, int | float):
        # Unix epoch (seconds or milliseconds)
        if s > 1e12:
            s = s / 1000.0
        return datetime.utcfromtimestamp(s)
    raw = str(s).strip()
    if not raw:
        raise ValueError("missing_ts")
    # Drop trailing Z and truncate fractional seconds for simpler formats
    s = raw.replace("Z", "").replace("z", "").strip()
    # Strip fractional seconds so we can try without .%f first
    s_no_fraction = s.split(".")[0] if "." in s and "T" in s else s
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d",
        "%Y%m%d",  # compact: 20250615
        "%Y%m%d%H%M%S",
        "%Y%m%d %H%M%S",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y",
    ]
    for fmt in formats:
        try:
            target = s_no_fraction if ".%f" not in fmt else s
            return datetime.strptime(target, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {raw!r}")


def _risk_band_to_base_risk(v: Any) -> float:
    if v is None:
        return 10.0
    s = str(v).strip().lower()
    if s in ("low", "l", "1"):
        return 5.0
    if s in ("medium", "med", "m", "2"):
        return 15.0
    if s in ("high", "h", "3"):
        return 25.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 10.0


def normalize_row(
    row: dict[str, Any],
    column_map: dict[str, str],
) -> tuple[dict[str, Any], str | None]:
    """
    Map a raw row (CSV dict or JSON object) to canonical field dict.
    Returns (canonical_dict, external_id_override or None).
    Raises ValueError on parse errors for required fields.
    """
    # Map external key -> value for canonical key
    canonical_raw: dict[str, Any] = {}
    external_id_override: str | None = None

    for external_key, canonical_key in column_map.items():
        if external_key not in row:
            continue
        val = row[external_key]
        if val is None or (isinstance(val, str) and not val.strip()):
            continue
        canonical_raw[canonical_key] = val

    # Apply type coercion and defaults
    out: dict[str, Any] = {}

    # Required
    iban = canonical_raw.get("iban_or_acct") or ""
    out["iban_or_acct"] = str(iban).strip() if iban else ""
    ts_val = canonical_raw.get("ts")
    if ts_val is None or (isinstance(ts_val, str) and not str(ts_val).strip()):
        raise ValueError("missing_ts")
    out["ts"] = _parse_ts(ts_val)
    amt_val = canonical_raw.get("amount")
    if amt_val is not None:
        if isinstance(amt_val, int | float):
            try:
                out["amount"] = float(amt_val)
            except (TypeError, ValueError):
                out["amount"] = 0.0
        else:
            # Strip currency symbols, commas, spaces (e.g. "1,234.56" or "£ 1 234.56")
            a = str(amt_val).strip().replace(",", "").replace(" ", "")
            for sym in ("$", "£", "€", "USD", "GBP", "EUR"):
                if a.startswith(sym) or a.endswith(sym):
                    a = a.replace(sym, "").strip()
            if not a:
                out["amount"] = 0.0
            else:
                try:
                    out["amount"] = float(a)
                except (TypeError, ValueError) as e:
                    raise ValueError(f"invalid amount: {amt_val!r}") from e
    else:
        out["amount"] = 0.0
    # If amount came from a "minor units" column (e.g. cents), convert to major units
    amount_src_keys = [k for k, v in column_map.items() if v == "amount"]
    if any("minor" in k.lower() for k in amount_src_keys):
        out["amount"] = out["amount"] / 100.0

    # Optional with defaults
    out["customer_name"] = (str(canonical_raw.get("customer_name") or "").strip()) or "Unknown"
    country = (str(canonical_raw.get("country") or "").strip() or "XXX")[:3]
    out["country"] = country
    out["currency"] = (str(canonical_raw.get("currency") or "USD").strip())[:3]
    out["merchant"] = (str(canonical_raw.get("merchant") or "").strip()) or None
    out["counterparty"] = (str(canonical_raw.get("counterparty") or "").strip()) or None
    out["country_txn"] = (str(canonical_raw.get("country_txn") or "").strip()) or None
    out["channel"] = (str(canonical_raw.get("channel") or "").strip()) or None
    out["direction"] = (str(canonical_raw.get("direction") or "").strip()) or None
    out["base_risk"] = _risk_band_to_base_risk(canonical_raw.get("base_risk"))

    # External id from dedicated column (e.g. transaction_id)
    for ext_key in EXTERNAL_ID_SOURCE_ALIASES:
        if ext_key in row and row[ext_key]:
            v = row[ext_key]
            if isinstance(v, str) and v.strip():
                external_id_override = v.strip()
                break
            if v is not None and str(v).strip():
                external_id_override = str(v).strip()
                break

    return out, external_id_override


# ---------------------------------------------------------------------------
# Persisted schema: learn once, reuse without code changes
# ---------------------------------------------------------------------------


def schema_file_for(data_path: str | Path) -> Path:
    """Path to the schema file for this data file (e.g. data/real/transactions.schema.json)."""
    p = Path(data_path)
    return p.parent / (p.stem + SCHEMA_FILENAME_SUFFIX)


def load_schema_file(data_path: str | Path) -> dict[str, str] | None:
    """
    Load column_map from the schema file next to the data file, if it exists.
    Returns None if file missing or invalid. Enables the engine to reuse
    a previously learned mapping without re-inferring.
    """
    path = schema_file_for(data_path)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        column_map = data.get("column_map")
        if isinstance(column_map, dict) and column_map:
            return column_map
    except (json.JSONDecodeError, OSError):
        pass
    return None


def save_schema_file(
    data_path: str | Path,
    column_map: dict[str, str],
    headers: list[str] | None = None,
) -> Path:
    """
    Persist the column map next to the data file so future ingests can load it.
    This is how the engine "learns from the data" independently: first run
    infers (or user runs discover --save), then saved schema is reused.
    """
    path = schema_file_for(data_path)
    payload: dict[str, Any] = {
        "column_map": column_map,
        "source_file": Path(data_path).name,
    }
    if headers:
        payload["headers"] = headers
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path
