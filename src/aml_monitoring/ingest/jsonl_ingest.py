"""JSONL ingestion into database."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from aml_monitoring import ENGINE_VERSION, RULES_VERSION
from aml_monitoring.audit_context import get_actor, get_correlation_id
from aml_monitoring.config import get_config, get_config_hash
from aml_monitoring.db import session_scope
from aml_monitoring.ingest._idempotency import compute_external_id
from aml_monitoring.models import Account, AuditLog, Customer, Transaction


def _parse_ts(s: str) -> datetime:
    if isinstance(s, datetime):
        return s
    s = str(s).strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(s.replace("Z", "").strip(), fmt.replace("Z", ""))
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {s!r}")


def _ensure_customer_and_account(
    session, customer_name: str, country: str, iban_or_acct: str, base_risk: float
) -> int:
    from sqlalchemy import select

    stmt = select(Account).where(Account.iban_or_acct == iban_or_acct)
    row = session.execute(stmt).scalar_one_or_none()
    if row:
        return int(row.id)
    customer = Customer(
        name=customer_name,
        country=country,
        base_risk=base_risk,
    )
    session.add(customer)
    session.flush()
    account = Account(customer_id=customer.id, iban_or_acct=iban_or_acct)
    session.add(account)
    session.flush()
    return int(account.id)


def ingest_jsonl(
    filepath: str | Path,
    batch_size: int = 500,
    config_path: str | None = None,
) -> tuple[int, int]:
    """
    Idempotent ingest: JSONL with customer_name, country, iban_or_acct, ts, amount, etc.
    Uses external_id (deterministic hash) to skip duplicates.
    Returns (lines_read, rows_inserted). Writes audit log with config_hash, duration.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(str(path))
    config = get_config(config_path)
    config_hash = get_config_hash(config)
    start = time.perf_counter()
    lines_read = 0
    rows_inserted = 0
    rows_rejected = 0
    reject_reasons: list[str] = []
    max_reject_reasons = 500

    with open(path, encoding="utf-8") as f:
        batch: list[dict] = []
        for line in f:
            line = line.strip()
            if not line:
                continue
            lines_read += 1
            try:
                obj = json.loads(line)
                customer_name = obj.get("customer_name") or "Unknown"
                country = (obj.get("country") or "XXX")[:3]
                iban = (obj.get("iban_or_acct") or "").strip()
                if not iban:
                    rows_rejected += 1
                    if len(reject_reasons) < max_reject_reasons:
                        reject_reasons.append("missing_iban")
                    continue
                ts = _parse_ts(obj.get("ts", ""))
                amount = float(obj.get("amount", 0))
                currency = (obj.get("currency") or "USD")[:3]
                merchant = obj.get("merchant") or None
                counterparty = obj.get("counterparty") or None
                country_txn = obj.get("country_txn") or obj.get("country") or None
                channel = obj.get("channel") or None
                direction = obj.get("direction") or None
                base_risk = float(obj.get("base_risk", 10))
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                rows_rejected += 1
                if len(reject_reasons) < max_reject_reasons:
                    reject_reasons.append(f"parse_error:{type(e).__name__}")
                continue
            batch.append(
                {
                    "customer_name": customer_name,
                    "country": country,
                    "iban_or_acct": iban,
                    "ts": ts,
                    "amount": amount,
                    "currency": currency,
                    "merchant": merchant,
                    "counterparty": counterparty,
                    "country_txn": country_txn,
                    "channel": channel,
                    "direction": direction,
                    "base_risk": base_risk,
                }
            )
            if len(batch) >= batch_size:
                with session_scope() as session:
                    seen_in_batch: set[str] = set()
                    for b in batch:
                        account_id = _ensure_customer_and_account(
                            session,
                            b["customer_name"],
                            b["country"],
                            b["iban_or_acct"],
                            b["base_risk"],
                        )
                        external_id = compute_external_id(
                            account_id,
                            b["ts"],
                            b["amount"],
                            b["currency"],
                            b["counterparty"],
                            b["direction"],
                        )
                        if (
                            external_id in seen_in_batch
                            or session.execute(
                                select(Transaction.id).where(Transaction.external_id == external_id)
                            ).first()
                        ):
                            continue
                        seen_in_batch.add(external_id)
                        t = Transaction(
                            external_id=external_id,
                            account_id=account_id,
                            ts=b["ts"],
                            amount=b["amount"],
                            currency=b["currency"],
                            merchant=b["merchant"],
                            counterparty=b["counterparty"],
                            country=b["country_txn"],
                            channel=b["channel"],
                            direction=b["direction"],
                        )
                        session.add(t)
                        rows_inserted += 1
                batch = []

    if batch:
        with session_scope() as session:
            seen_residual: set[str] = set()
            for b in batch:
                account_id = _ensure_customer_and_account(
                    session,
                    b["customer_name"],
                    b["country"],
                    b["iban_or_acct"],
                    b["base_risk"],
                )
                external_id = compute_external_id(
                    account_id,
                    b["ts"],
                    b["amount"],
                    b["currency"],
                    b["counterparty"],
                    b["direction"],
                )
                if (
                    external_id in seen_residual
                    or session.execute(
                        select(Transaction.id).where(Transaction.external_id == external_id)
                    ).first()
                ):
                    continue
                seen_residual.add(external_id)
                t = Transaction(
                    external_id=external_id,
                    account_id=account_id,
                    ts=b["ts"],
                    amount=b["amount"],
                    currency=b["currency"],
                    merchant=b["merchant"],
                    counterparty=b["counterparty"],
                    country=b["country_txn"],
                    channel=b["channel"],
                    direction=b["direction"],
                )
                session.add(t)
                rows_inserted += 1

    duration = time.perf_counter() - start
    details: dict = {
        "rows_read": lines_read,
        "rows_inserted": rows_inserted,
        "duration_seconds": round(duration, 3),
        "config_hash": config_hash,
        "rules_version": RULES_VERSION,
        "engine_version": ENGINE_VERSION,
    }
    if rows_rejected:
        details["rows_rejected"] = rows_rejected
        details["reject_reasons"] = reject_reasons
    with session_scope() as session:
        session.add(
            AuditLog(
                correlation_id=get_correlation_id(),
                action="ingest",
                entity_type="file",
                entity_id=str(path),
                actor=get_actor(),
                details_json=details,
            )
        )
    return lines_read, rows_inserted
