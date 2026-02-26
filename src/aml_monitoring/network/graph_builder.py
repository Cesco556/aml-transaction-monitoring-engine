"""Build/update relationship edges from transactions."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from logging import getLogger

from sqlalchemy import select

from aml_monitoring.audit_context import get_actor, get_correlation_id
from aml_monitoring.db import session_scope
from aml_monitoring.models import AuditLog, RelationshipEdge, Transaction

logger = getLogger(__name__)


def _norm(s: str | None) -> str:
    if s is None or not s.strip():
        return ""
    return s.strip().lower()


def build_network(config_path: str | None = None) -> dict:
    """
    Build or update relationship edges from all transactions.
    Edges: account->counterparty, account->merchant, customer->counterparty.
    Returns dict with edge_count, duration_seconds. Writes AuditLog network_build.
    """
    from aml_monitoring.config import get_config

    get_config(config_path)
    cid = get_correlation_id()
    actor = get_actor()
    start = time.perf_counter()
    edge_count = 0

    with session_scope() as session:
        stmt = select(Transaction).order_by(Transaction.id)
        txns = list(session.execute(stmt).scalars().all())
        # Group by (src_type, src_id, dst_type, dst_key) -> (first_ts, last_ts, count)
        agg: dict[tuple[str, int, str, str], tuple[datetime, datetime, int]] = {}
        for txn in txns:
            acct = txn.account
            cust = acct.customer
            ts = txn.ts if txn.ts.tzinfo else txn.ts.replace(tzinfo=UTC)
            norm_cp = _norm(txn.counterparty)
            norm_merchant = _norm(txn.merchant) if txn.merchant else ""

            if norm_cp:
                key_a_cp = ("account", txn.account_id, "counterparty", norm_cp)
                if key_a_cp not in agg:
                    agg[key_a_cp] = (ts, ts, 0)
                first_ts, last_ts, cnt = agg[key_a_cp]
                agg[key_a_cp] = (min(first_ts, ts), max(last_ts, ts), cnt + 1)

                key_c_cp = ("customer", cust.id, "counterparty", norm_cp)
                if key_c_cp not in agg:
                    agg[key_c_cp] = (ts, ts, 0)
                first_ts, last_ts, cnt = agg[key_c_cp]
                agg[key_c_cp] = (min(first_ts, ts), max(last_ts, ts), cnt + 1)

            if norm_merchant:
                key_a_m = ("account", txn.account_id, "merchant", norm_merchant)
                if key_a_m not in agg:
                    agg[key_a_m] = (ts, ts, 0)
                first_ts, last_ts, cnt = agg[key_a_m]
                agg[key_a_m] = (min(first_ts, ts), max(last_ts, ts), cnt + 1)

        for (src_type, src_id, dst_type, dst_key), (first_ts, last_ts, count) in agg.items():
            existing = session.execute(
                select(RelationshipEdge).where(
                    RelationshipEdge.src_type == src_type,
                    RelationshipEdge.src_id == src_id,
                    RelationshipEdge.dst_type == dst_type,
                    RelationshipEdge.dst_key == dst_key,
                )
            ).scalar_one_or_none()
            if existing:
                f = existing.first_seen_at
                last_seen = existing.last_seen_at
                if f is not None and getattr(f, "tzinfo", None) is None:
                    f = f.replace(tzinfo=UTC)
                if last_seen is not None and getattr(last_seen, "tzinfo", None) is None:
                    last_seen = last_seen.replace(tzinfo=UTC)
                existing.first_seen_at = min(f, first_ts)
                existing.last_seen_at = max(last_seen, last_ts)
                existing.txn_count = count
                existing.correlation_id = cid
            else:
                session.add(
                    RelationshipEdge(
                        src_type=src_type,
                        src_id=src_id,
                        dst_type=dst_type,
                        dst_key=dst_key,
                        first_seen_at=first_ts,
                        last_seen_at=last_ts,
                        txn_count=count,
                        correlation_id=cid,
                    )
                )
            edge_count += 1

        duration = time.perf_counter() - start
        session.add(
            AuditLog(
                correlation_id=cid,
                action="network_build",
                entity_type="batch",
                entity_id="all",
                actor=actor,
                details_json={
                    "edge_count": edge_count,
                    "transaction_count": len(txns),
                    "duration_seconds": round(duration, 3),
                },
            )
        )
    return {"edge_count": edge_count, "duration_seconds": round(duration, 3)}
