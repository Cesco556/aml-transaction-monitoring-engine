"""Path analysis: shortest paths, all paths, and money flow tracing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import networkx as nx
from sqlalchemy import select

from aml_monitoring.models import Transaction


@dataclass
class FlowNode:
    """A node in the money flow tree."""

    account_id: int
    amount: float = 0.0
    transaction_count: int = 0
    children: list[FlowNode] = field(default_factory=list)


def find_shortest_path(
    graph: nx.DiGraph, source_id: int, target_id: int
) -> list[int]:
    """
    Find shortest path between two accounts in the graph.

    Returns:
        List of account_ids from source to target.
        Empty list if no path exists.
    """
    if source_id not in graph or target_id not in graph:
        return []

    try:
        # Use undirected view for reachability (money can flow either way)
        undirected = graph.to_undirected()
        return nx.shortest_path(undirected, source_id, target_id)
    except nx.NetworkXNoPath:
        return []


def find_all_paths(
    graph: nx.DiGraph,
    source_id: int,
    target_id: int,
    max_hops: int = 4,
) -> list[list[int]]:
    """
    Find all simple paths between two accounts up to max_hops.

    Returns:
        List of paths, each path being a list of account_ids.
    """
    if source_id not in graph or target_id not in graph:
        return []

    try:
        undirected = graph.to_undirected()
        return list(
            nx.all_simple_paths(undirected, source_id, target_id, cutoff=max_hops)
        )
    except nx.NetworkXNoPath:
        return []


def trace_money_flow(
    session: Any,
    account_id: int,
    direction: str = "out",
    max_depth: int = 3,
    lookback_days: int = 90,
) -> FlowNode:
    """
    Trace money flow from/to an account as a hierarchical FlowTree.

    Follows transaction counterparties to find where money goes (out)
    or comes from (in).

    Args:
        session: DB session.
        account_id: Starting account.
        direction: "out" (where money goes) or "in" (where it comes from).
        max_depth: Maximum hops to trace.
        lookback_days: Only consider transactions within this window.

    Returns:
        FlowNode tree rooted at account_id.
    """
    from aml_monitoring.models import Account

    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)

    # Build a map: account_id -> [(counterparty, total_amount, txn_count)]
    dir_filter = "out" if direction == "out" else "in"

    root = FlowNode(account_id=account_id)
    visited: set[int] = {account_id}

    def _trace(node: FlowNode, depth: int) -> None:
        if depth >= max_depth:
            return

        # Get transactions for this account in the given direction
        stmt = select(Transaction).where(
            Transaction.account_id == node.account_id,
            Transaction.ts >= cutoff,
        )
        if dir_filter == "out":
            stmt = stmt.where(Transaction.direction == "out")
        else:
            stmt = stmt.where(Transaction.direction == "in")

        txns = list(session.execute(stmt).scalars().all())

        # Group by counterparty
        cp_agg: dict[str, tuple[float, int]] = {}
        for txn in txns:
            cp = txn.counterparty
            if not cp:
                continue
            cp_norm = cp.strip().lower()
            amt, cnt = cp_agg.get(cp_norm, (0.0, 0))
            cp_agg[cp_norm] = (amt + abs(txn.amount), cnt + 1)

        # Try to resolve counterparties to account IDs
        for cp_key, (total_amt, txn_count) in cp_agg.items():
            # Look for accounts whose IBAN matches the counterparty
            acct = session.execute(
                select(Account).where(Account.iban_or_acct == cp_key)
            ).scalar_one_or_none()

            if acct and acct.id not in visited:
                child = FlowNode(
                    account_id=acct.id,
                    amount=total_amt,
                    transaction_count=txn_count,
                )
                node.children.append(child)
                visited.add(acct.id)
                _trace(child, depth + 1)
            elif not acct:
                # External counterparty — represent as negative ID (unresolved)
                child = FlowNode(
                    account_id=-1,
                    amount=total_amt,
                    transaction_count=txn_count,
                )
                node.children.append(child)

    _trace(root, 0)
    return root


def flow_tree_to_dict(node: FlowNode) -> dict:
    """Convert FlowNode tree to a serializable dict."""
    return {
        "account_id": node.account_id,
        "amount": round(node.amount, 2),
        "transaction_count": node.transaction_count,
        "children": [flow_tree_to_dict(c) for c in node.children],
    }
