"""SAR-like report generation (JSON + CSV)."""

from __future__ import annotations

import csv
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from aml_monitoring import ENGINE_VERSION, RULES_VERSION
from aml_monitoring.audit_context import get_actor, get_correlation_id
from aml_monitoring.config import get_config, get_config_hash
from aml_monitoring.models import Alert, AuditLog, Transaction


def generate_sar_report(
    session,
    output_dir: str | Path,
    output_prefix: str = "sar",
    include_evidence: bool = True,
    config_path: str | None = None,
) -> tuple[str, str]:
    """
    Query alerts with transaction details, write JSON and CSV.
    Writes audit log with counts, duration, config_hash, rules_version.
    Returns (path_json, path_csv).
    """
    start = time.perf_counter()
    config = get_config(config_path)
    config_hash = get_config_hash(config)
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    ts_suffix = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = path / f"{output_prefix}_{ts_suffix}.json"
    csv_path = path / f"{output_prefix}_{ts_suffix}.csv"

    stmt = (
        select(
            Alert.id,
            Alert.transaction_id,
            Alert.rule_id,
            Alert.severity,
            Alert.reason,
            Alert.evidence_fields,
            Alert.created_at,
            Alert.updated_at,
            Transaction.amount,
            Transaction.currency,
            Transaction.ts,
            Transaction.account_id,
            Transaction.counterparty,
            Transaction.country,
        )
        .join(Transaction, Transaction.id == Alert.transaction_id)
        .order_by(Alert.created_at)
    )
    rows = session.execute(stmt).fetchall()
    records: list[dict[str, Any]] = []
    for r in rows:
        created_at = r[6]
        updated_at = r[7]
        hours_to_disposition: float | None = None
        if (
            created_at
            and updated_at
            and hasattr(created_at, "timestamp")
            and hasattr(updated_at, "timestamp")
        ):
            delta = (
                updated_at
                if updated_at.tzinfo
                else updated_at.replace(tzinfo=UTC)
                - (created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC))
            )
            hours_to_disposition = round(delta.total_seconds() / 3600.0, 2)
        records.append(
            {
                "alert_id": r[0],
                "transaction_id": r[1],
                "rule_id": r[2],
                "severity": r[3],
                "reason": r[4],
                "evidence": r[5] if include_evidence else None,
                "created_at": (
                    created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
                ),
                "updated_at": (
                    updated_at.isoformat()
                    if updated_at and hasattr(updated_at, "isoformat")
                    else (str(updated_at) if updated_at else None)
                ),
                "hours_to_disposition": hours_to_disposition,
                "amount": r[8],
                "currency": r[9],
                "ts": r[10].isoformat() if hasattr(r[10], "isoformat") else str(r[10]),
                "account_id": r[11],
                "counterparty": r[12],
                "country": r[13],
            }
        )

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {"generated_at": datetime.now(UTC).isoformat(), "alerts": records},
            f,
            indent=2,
        )

    fieldnames = [
        "alert_id",
        "transaction_id",
        "rule_id",
        "severity",
        "reason",
        "created_at",
        "updated_at",
        "hours_to_disposition",
        "amount",
        "currency",
        "ts",
        "account_id",
        "counterparty",
        "country",
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for rec in records:
            row = dict(rec)
            row.pop("evidence", None)
            w.writerow(row)

    duration = time.perf_counter() - start
    session.add(
        AuditLog(
            correlation_id=get_correlation_id(),
            action="generate_report",
            entity_type="report",
            entity_id=ts_suffix,
            actor=get_actor(),
            details_json={
                "alert_count": len(records),
                "duration_seconds": round(duration, 3),
                "config_hash": config_hash,
                "rules_version": RULES_VERSION,
                "engine_version": ENGINE_VERSION,
                "output_json": str(json_path),
                "output_csv": str(csv_path),
            },
        )
    )
    return str(json_path), str(csv_path)
