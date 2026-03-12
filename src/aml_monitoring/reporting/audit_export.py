"""Audit export — generate a complete examiner-ready ZIP package."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from aml_monitoring.config import get_config, get_config_hash
from aml_monitoring.models import Alert, AuditLog, Case, CaseItem, CaseNote, Transaction


def _serialize_dt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _verify_audit_chain(logs: list[AuditLog]) -> dict[str, Any]:
    """Verify hash chain integrity of audit logs.

    Returns dict with verification status and details.
    """
    if not logs:
        return {"verified": True, "total": 0, "broken_at": None}

    broken_at: int | None = None
    for i, log in enumerate(logs):
        if log.row_hash is None:
            # Logs without hashes (pre-chain era) — skip
            continue
        expected_prev = logs[i - 1].row_hash if i > 0 else None
        if log.prev_hash != expected_prev:
            broken_at = log.id
            break

    return {
        "verified": broken_at is None,
        "total": len(logs),
        "broken_at": broken_at,
    }


def _dict_rows(objects: list, columns: list[str]) -> list[dict[str, Any]]:
    """Convert ORM objects to list of dicts."""
    rows = []
    for obj in objects:
        row = {}
        for col in columns:
            val = getattr(obj, col, None)
            if isinstance(val, datetime):
                val = val.isoformat()
            elif isinstance(val, dict):
                val = json.dumps(val, default=str)
            row[col] = val
        rows.append(row)
    return rows


def _write_csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    """Write dicts to CSV bytes."""
    if not rows:
        return b""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def export_audit_package(
    session,
    date_from: datetime,
    date_to: datetime,
    output_dir: str | Path,
    config_path: str | None = None,
) -> str:
    """Generate a complete audit package for examiner review.

    Args:
        session: SQLAlchemy session.
        date_from: Start of audit period (inclusive).
        date_to: End of audit period (inclusive).
        output_dir: Directory where the ZIP file will be written.
        config_path: Optional config path.

    Returns:
        Absolute path to the generated ZIP file.
    """
    config = get_config(config_path)
    config_hash = get_config_hash(config)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ts_suffix = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    zip_name = f"audit_export_{ts_suffix}.zip"
    zip_path = out_dir / zip_name

    # Ensure timezone-aware bounds
    if date_from.tzinfo is None:
        date_from = date_from.replace(tzinfo=UTC)
    if date_to.tzinfo is None:
        date_to = date_to.replace(tzinfo=UTC)

    # --- Collect data ---

    # Alerts in range
    alerts = session.execute(
        select(Alert)
        .where(Alert.created_at >= date_from)
        .where(Alert.created_at <= date_to)
        .order_by(Alert.created_at)
    ).scalars().all()

    alert_cols = [
        "id", "transaction_id", "rule_id", "severity", "score", "reason",
        "evidence_fields", "config_hash", "rules_version", "status",
        "disposition", "created_at", "updated_at",
    ]
    alert_rows = _dict_rows(alerts, alert_cols)

    # Cases (any case with linked alerts in date range)
    alert_ids = [a.id for a in alerts]
    case_ids: set[int] = set()
    if alert_ids:
        items = session.execute(
            select(CaseItem).where(CaseItem.alert_id.in_(alert_ids))
        ).scalars().all()
        case_ids = {i.case_id for i in items}

    cases: list[Case] = []
    if case_ids:
        cases = session.execute(
            select(Case).where(Case.id.in_(case_ids)).order_by(Case.id)
        ).scalars().all()

    case_cols = ["id", "status", "priority", "assigned_to", "created_at", "updated_at", "actor"]
    case_rows = _dict_rows(cases, case_cols)

    # Case notes
    notes: list[CaseNote] = []
    if case_ids:
        notes = session.execute(
            select(CaseNote)
            .where(CaseNote.case_id.in_(case_ids))
            .order_by(CaseNote.created_at)
        ).scalars().all()

    note_cols = ["id", "case_id", "note", "actor", "correlation_id", "created_at"]
    note_rows = _dict_rows(notes, note_cols)

    # Audit logs in range
    audit_logs = session.execute(
        select(AuditLog)
        .where(AuditLog.ts >= date_from)
        .where(AuditLog.ts <= date_to)
        .order_by(AuditLog.id)
    ).scalars().all()

    audit_cols = [
        "id", "correlation_id", "action", "entity_type", "entity_id",
        "ts", "actor", "details_json", "prev_hash", "row_hash",
    ]
    audit_rows = _dict_rows(audit_logs, audit_cols)

    # Chain verification
    chain_result = _verify_audit_chain(audit_logs)

    # Summary statistics
    summary = {
        "export_generated_at": datetime.now(UTC).isoformat(),
        "period_from": date_from.isoformat(),
        "period_to": date_to.isoformat(),
        "config_hash": config_hash,
        "total_alerts": len(alerts),
        "total_cases": len(cases),
        "total_notes": len(notes),
        "total_audit_logs": len(audit_logs),
        "alerts_by_severity": {},
        "alerts_by_disposition": {},
        "cases_by_status": {},
        "audit_chain_verification": chain_result,
    }
    for a in alerts:
        summary["alerts_by_severity"][a.severity] = (
            summary["alerts_by_severity"].get(a.severity, 0) + 1
        )
        disp = a.disposition or "pending"
        summary["alerts_by_disposition"][disp] = (
            summary["alerts_by_disposition"].get(disp, 0) + 1
        )
    for c in cases:
        summary["cases_by_status"][c.status] = (
            summary["cases_by_status"].get(c.status, 0) + 1
        )

    # --- Write ZIP ---
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # JSON files
        zf.writestr("alerts.json", json.dumps(alert_rows, indent=2, default=str))
        zf.writestr("cases.json", json.dumps(case_rows, indent=2, default=str))
        zf.writestr("case_notes.json", json.dumps(note_rows, indent=2, default=str))
        zf.writestr("audit_logs.json", json.dumps(audit_rows, indent=2, default=str))
        zf.writestr("summary.json", json.dumps(summary, indent=2, default=str))

        # CSV files
        if alert_rows:
            zf.writestr("alerts.csv", _write_csv_bytes(alert_rows).decode())
        if case_rows:
            zf.writestr("cases.csv", _write_csv_bytes(case_rows).decode())
        if note_rows:
            zf.writestr("case_notes.csv", _write_csv_bytes(note_rows).decode())
        if audit_rows:
            zf.writestr("audit_logs.csv", _write_csv_bytes(audit_rows).decode())

    return str(zip_path.resolve())
