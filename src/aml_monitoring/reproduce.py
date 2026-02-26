"""Reproduce a run by correlation_id: export audit logs, alerts, cases, network to a JSON bundle."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from aml_monitoring.audit_context import get_actor
from aml_monitoring.db import session_scope
from aml_monitoring.models import Alert, AuditLog, Case, RelationshipEdge, Transaction


def _serialize_dt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat() if dt.tzinfo else dt.replace(tzinfo=UTC).isoformat()


def _audit_log_row_to_dict(row: AuditLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "correlation_id": row.correlation_id,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "ts": _serialize_dt(row.ts),
        "actor": row.actor,
        "details_json": row.details_json,
    }


def _alert_to_dict(a: Alert) -> dict[str, Any]:
    return {
        "id": a.id,
        "transaction_id": a.transaction_id,
        "rule_id": a.rule_id,
        "severity": a.severity,
        "score": a.score,
        "reason": a.reason,
        "evidence_fields": a.evidence_fields,
        "config_hash": a.config_hash,
        "rules_version": a.rules_version,
        "engine_version": a.engine_version,
        "correlation_id": a.correlation_id,
        "status": a.status,
        "disposition": a.disposition,
        "created_at": _serialize_dt(a.created_at),
        "updated_at": _serialize_dt(a.updated_at),
    }


def _case_to_dict(c: Case) -> dict[str, Any]:
    items = [
        {
            "id": i.id,
            "case_id": i.case_id,
            "alert_id": i.alert_id,
            "transaction_id": i.transaction_id,
            "created_at": _serialize_dt(i.created_at),
        }
        for i in c.items
    ]
    notes = [
        {
            "id": n.id,
            "case_id": n.case_id,
            "note": n.note,
            "created_at": _serialize_dt(n.created_at),
            "actor": n.actor,
            "correlation_id": n.correlation_id,
        }
        for n in c.notes
    ]
    return {
        "id": c.id,
        "status": c.status,
        "priority": c.priority,
        "assigned_to": c.assigned_to,
        "created_at": _serialize_dt(c.created_at),
        "updated_at": _serialize_dt(c.updated_at),
        "correlation_id": c.correlation_id,
        "actor": c.actor,
        "items": items,
        "notes": notes,
    }


def _edge_to_dict(e: RelationshipEdge) -> dict[str, Any]:
    return {
        "id": e.id,
        "src_type": e.src_type,
        "src_id": e.src_id,
        "dst_type": e.dst_type,
        "dst_key": e.dst_key,
        "first_seen_at": _serialize_dt(e.first_seen_at),
        "last_seen_at": _serialize_dt(e.last_seen_at),
        "txn_count": e.txn_count,
        "correlation_id": e.correlation_id,
    }


def _transaction_to_dict(t: Transaction) -> dict[str, Any]:
    """Serialize transaction for replay; required keys for replay."""
    return {
        "id": t.id,
        "external_id": t.external_id,
        "account_id": t.account_id,
        "ts": _serialize_dt(t.ts),
        "amount": t.amount,
        "currency": t.currency or "USD",
        "merchant": t.merchant,
        "counterparty": t.counterparty,
        "country": t.country,
        "channel": t.channel,
        "direction": t.direction,
        "risk_score": t.risk_score,
        "config_hash": t.config_hash,
        "rules_version": t.rules_version,
        "engine_version": t.engine_version,
    }


def reproduce_run(
    correlation_id: str,
    out_path: str | Path | None = None,
    config_path: str | None = None,
) -> str:
    """
    Query DB for all data tied to the given correlation_id; write a JSON bundle and an AuditLog.
    Returns the path where the bundle was written.
    """
    from aml_monitoring.config import get_config
    from aml_monitoring.db import init_db

    if config_path is not None:
        config = get_config(config_path)
        db_url = config.get("database", {}).get("url", "sqlite:///./data/aml.db")
        init_db(db_url, echo=False)

    bundle: dict[str, Any] = {
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "correlation_id": correlation_id,
        },
        "config": {
            "config_hashes": [],
            "rules_versions": [],
            "engine_versions": [],
            "resolved": None,
        },
        "audit_logs": [],
        "alerts": [],
        "transactions": [],
        "cases": [],
        "network": {"edge_count": 0, "edges": []},
    }

    config_hashes: set[str] = set()
    rules_versions: set[str] = set()
    engine_versions: set[str] = set()

    with session_scope() as session:
        audit_rows = list(
            session.execute(
                select(AuditLog)
                .where(AuditLog.correlation_id == correlation_id)
                .order_by(AuditLog.ts)
            )
            .scalars()
            .all()
        )
        for row in audit_rows:
            bundle["audit_logs"].append(_audit_log_row_to_dict(row))
            if row.details_json and isinstance(row.details_json, dict):
                ch = row.details_json.get("config_hash")
                if ch:
                    config_hashes.add(ch)

        alerts = list(
            session.execute(
                select(Alert).where(Alert.correlation_id == correlation_id).order_by(Alert.id)
            )
            .scalars()
            .all()
        )
        txn_ids: set[int] = {a.transaction_id for a in alerts}
        if txn_ids:
            txns = list(
                session.execute(
                    select(Transaction).where(Transaction.id.in_(txn_ids)).order_by(Transaction.id)
                )
                .scalars()
                .all()
            )
            for t in txns:
                bundle["transactions"].append(_transaction_to_dict(t))

        for a in alerts:
            bundle["alerts"].append(_alert_to_dict(a))
            if a.config_hash:
                config_hashes.add(a.config_hash)
            if a.rules_version:
                rules_versions.add(a.rules_version)
            if a.engine_version:
                engine_versions.add(a.engine_version)

        cases = list(
            session.execute(
                select(Case)
                .where(Case.correlation_id == correlation_id)
                .options(selectinload(Case.items), selectinload(Case.notes))
            )
            .scalars()
            .all()
        )
        for c in cases:
            bundle["cases"].append(_case_to_dict(c))

        edges = list(
            session.execute(
                select(RelationshipEdge)
                .where(RelationshipEdge.correlation_id == correlation_id)
                .order_by(RelationshipEdge.id)
            )
            .scalars()
            .all()
        )
        for e in edges:
            bundle["network"]["edges"].append(_edge_to_dict(e))
        bundle["network"]["edge_count"] = len(edges)

        bundle["config"]["config_hashes"] = sorted(config_hashes)
        bundle["config"]["rules_versions"] = sorted(rules_versions)
        bundle["config"]["engine_versions"] = sorted(engine_versions)

    resolved = get_config(config_path) if config_path else get_config()
    bundle["config"]["resolved"] = resolved

    if out_path is None:
        out_path = Path(".") / f"reproduce_{correlation_id}.json"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2)

    repro_cid = str(uuid.uuid4())
    with session_scope() as session:
        session.add(
            AuditLog(
                correlation_id=repro_cid,
                action="reproduce_run",
                entity_type="run",
                entity_id=correlation_id,
                actor=get_actor(),
                details_json={
                    "target_correlation_id": correlation_id,
                    "output_path": str(out_path.resolve()),
                },
            )
        )
    return str(out_path.resolve())
