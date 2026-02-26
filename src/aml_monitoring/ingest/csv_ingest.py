"""CSV ingestion into database - use standard csv when possible."""

from __future__ import annotations

import csv
import logging
import time
from pathlib import Path

from sqlalchemy import select

from aml_monitoring import ENGINE_VERSION, RULES_VERSION
from aml_monitoring.audit_context import get_actor, get_correlation_id
from aml_monitoring.config import get_config, get_config_hash
from aml_monitoring.db import session_scope
from aml_monitoring.ingest._idempotency import external_id_for_row
from aml_monitoring.ingest.schema import (
    infer_column_map,
    load_schema_file,
    normalize_row,
    save_schema_file,
)
from aml_monitoring.models import Account, AuditLog, Customer, Transaction

log = logging.getLogger(__name__)


def _ensure_customer_and_account(
    session, customer_name: str, country: str, iban_or_acct: str, base_risk: float
) -> int:
    """Get or create customer and account; return account_id."""
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


def ingest_csv(
    filepath: str | Path,
    encoding: str = "utf-8",
    batch_size: int = 500,
    config_path: str | None = None,
    save_schema: bool = False,
) -> tuple[int, int]:
    """
    Idempotent ingest from CSV. Column mapping is resolved in order:
    1. config ingest.column_map (if set)
    2. schema file next to the data (e.g. transactions.schema.json) if present
    3. inferred from CSV headers (engine learns from the data)
    With save_schema=True, the inferred map is written to the schema file for reuse.
    Returns (rows_read, rows_inserted). Writes audit log with config_hash, duration.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(str(path))
    config = get_config(config_path)
    config_hash = get_config_hash(config)
    ingest_cfg = config.get("ingest") or {}
    config_column_map = ingest_cfg.get("column_map")
    start = time.perf_counter()
    rows_read = 0
    rows_inserted = 0
    rows_rejected = 0
    reject_reasons: list[str] = []
    max_reject_reasons = 500  # cap to avoid huge audit payload

    with open(path, encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return 0, 0
        headers = [h for h in reader.fieldnames if h]
        # Learn from data: config > persisted schema file > infer from headers
        column_map = config_column_map or load_schema_file(path) or infer_column_map(headers, None)
        used_persisted_schema = bool(not config_column_map and load_schema_file(path))
        inferred = not config_column_map and not used_persisted_schema
        canonical_fields_mapped = set(column_map.values())
        if "ts" not in canonical_fields_mapped or "iban_or_acct" not in canonical_fields_mapped:
            missing = [f for f in ("ts", "iban_or_acct") if f not in canonical_fields_mapped]
            raise ValueError(
                f"Cannot ingest: no column mapped to required field(s) {missing}. "
                f"Headers: {headers}. Run 'aml discover {path}' to see inferred mapping, or add ingest.column_map in config."
            )
        batch: list[tuple[dict, str | None]] = []  # (canonical_dict, external_id_override)
        for row in reader:
            rows_read += 1
            try:
                canonical, ext_id = normalize_row(row, column_map)
                if not canonical.get("iban_or_acct"):
                    rows_rejected += 1
                    if len(reject_reasons) < max_reject_reasons:
                        reject_reasons.append("missing_iban")
                    continue
                batch.append((canonical, ext_id))
            except (ValueError, KeyError) as e:
                rows_rejected += 1
                if len(reject_reasons) < max_reject_reasons:
                    msg = str(e).replace("\n", " ")[:120]
                    reject_reasons.append(f"parse_error:{type(e).__name__}:{msg}")
                continue
            if len(batch) >= batch_size:
                with session_scope() as session:
                    seen_in_batch: set[str] = set()
                    for b, ext_id in batch:
                        account_id = _ensure_customer_and_account(
                            session,
                            b["customer_name"],
                            b["country"],
                            b["iban_or_acct"],
                            b["base_risk"],
                        )
                        external_id = external_id_for_row(
                            ext_id,
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
            for b, ext_id in batch:
                account_id = _ensure_customer_and_account(
                    session,
                    b["customer_name"],
                    b["country"],
                    b["iban_or_acct"],
                    b["base_risk"],
                )
                external_id = external_id_for_row(
                    ext_id,
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
        "rows_read": rows_read,
        "rows_inserted": rows_inserted,
        "duration_seconds": round(duration, 3),
        "config_hash": config_hash,
        "rules_version": RULES_VERSION,
        "engine_version": ENGINE_VERSION,
    }
    if rows_rejected:
        details["rows_rejected"] = rows_rejected
        details["reject_reasons"] = reject_reasons
        if rows_inserted == 0 and reject_reasons:
            log.warning(
                "All rows rejected. First reject reasons: %s",
                reject_reasons[:5],
            )
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
    # Persist learned mapping so future ingests reuse it without re-inferring
    if save_schema and inferred and column_map:
        save_schema_file(path, column_map, headers)
    return rows_read, rows_inserted
