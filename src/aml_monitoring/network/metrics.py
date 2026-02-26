"""Network metrics: ring signal (shared counterparties across accounts)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from aml_monitoring.models import RelationshipEdge


@dataclass
class RingSignal:
    """Ring signal for an account: overlap with other accounts via shared counterparties."""

    overlap_count: int
    shared_counterparties: list[str]
    linked_accounts: list[int]
    degree: int


def ring_signal(
    account_id: int,
    session: Any,
    lookback_days: int,
) -> RingSignal:
    """
    Compute ring signal for account: counterparties for this account, then other accounts
    sharing those counterparties. Returns overlap_count, shared_counterparties,
    linked_accounts, degree. Only uses edges within lookback_days (last_seen_at).
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=lookback_days)

    # Counterparties for this account in lookback window
    stmt_cp = (
        select(RelationshipEdge.dst_key)
        .where(RelationshipEdge.src_type == "account")
        .where(RelationshipEdge.src_id == account_id)
        .where(RelationshipEdge.dst_type == "counterparty")
        .where(RelationshipEdge.last_seen_at >= cutoff)
    )
    my_counterparties = {row[0] for row in session.execute(stmt_cp).all()}
    if not my_counterparties:
        return RingSignal(
            overlap_count=0,
            shared_counterparties=[],
            linked_accounts=[],
            degree=0,
        )

    # Other accounts that have any of these counterparties in lookback window
    stmt_other = (
        select(RelationshipEdge.src_id, RelationshipEdge.dst_key)
        .where(RelationshipEdge.src_type == "account")
        .where(RelationshipEdge.src_id != account_id)
        .where(RelationshipEdge.dst_type == "counterparty")
        .where(RelationshipEdge.dst_key.in_(my_counterparties))
        .where(RelationshipEdge.last_seen_at >= cutoff)
    )
    # account_id -> set of shared counterparty keys
    other_account_cps: dict[int, set[str]] = {}
    for aid, dst_key in session.execute(stmt_other).all():
        other_account_cps.setdefault(aid, set()).add(dst_key)

    linked_accounts = list(other_account_cps.keys())
    # Shared counterparties: union of all counterparties shared with linked accounts
    shared_set = set()
    for cps in other_account_cps.values():
        shared_set |= cps
    shared_counterparties = sorted(shared_set)
    overlap_count = len(shared_counterparties)
    degree = len(linked_accounts)

    return RingSignal(
        overlap_count=overlap_count,
        shared_counterparties=shared_counterparties,
        linked_accounts=sorted(linked_accounts),
        degree=degree,
    )
