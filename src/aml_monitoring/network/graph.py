"""Graph analysis engine: build in-memory networkx graphs from RelationshipEdge data."""

from __future__ import annotations

from typing import Any

import networkx as nx
from sqlalchemy import func, select

from aml_monitoring.models import Account, Alert, Customer, RelationshipEdge, Transaction


def build_transaction_graph(session: Any) -> nx.DiGraph:
    """
    Build a directed graph from RelationshipEdge data.
    Nodes = accounts, edges = account->account via shared counterparties.
    Node attrs: account_id, customer_name, country, total_txn_volume, alert_count.
    Edge attrs: txn_count, total_amount, first_seen, last_seen.
    """
    G = nx.DiGraph()

    # Load all accounts with customer info
    accounts = list(
        session.execute(
            select(Account, Customer).join(Customer, Account.customer_id == Customer.id)
        ).all()
    )

    # Pre-compute per-account aggregates
    txn_stats = dict(
        session.execute(
            select(
                Transaction.account_id,
                func.sum(Transaction.amount),
            ).group_by(Transaction.account_id)
        ).all()
    )

    alert_counts: dict[int, int] = {}
    rows = session.execute(
        select(Transaction.account_id, func.count(Alert.id))
        .join(Alert, Alert.transaction_id == Transaction.id)
        .group_by(Transaction.account_id)
    ).all()
    for acct_id, cnt in rows:
        alert_counts[acct_id] = cnt

    # Add nodes
    for acct, cust in accounts:
        G.add_node(
            acct.id,
            account_id=acct.id,
            customer_name=cust.name,
            country=cust.country,
            total_txn_volume=float(txn_stats.get(acct.id, 0) or 0),
            alert_count=alert_counts.get(acct.id, 0),
        )

    # Build edges: accounts sharing counterparties form directed edges.
    # For each counterparty, find all accounts that transact with it,
    # then create edges between them weighted by shared txn volume.
    cp_edges = list(
        session.execute(
            select(RelationshipEdge).where(
                RelationshipEdge.src_type == "account",
                RelationshipEdge.dst_type == "counterparty",
            )
        )
        .scalars()
        .all()
    )

    # Group by counterparty -> list of (account_id, edge)
    cp_map: dict[str, list[RelationshipEdge]] = {}
    for edge in cp_edges:
        cp_map.setdefault(edge.dst_key, []).append(edge)

    # For each counterparty shared by 2+ accounts, create account-to-account edges
    for cp_key, edges in cp_map.items():
        if len(edges) < 2:
            continue
        for i, e1 in enumerate(edges):
            for e2 in edges[i + 1 :]:
                # Bidirectional: both directions
                for src_edge, dst_edge in [(e1, e2), (e2, e1)]:
                    src_id = src_edge.src_id
                    dst_id = dst_edge.src_id
                    if G.has_edge(src_id, dst_id):
                        data = G[src_id][dst_id]
                        data["txn_count"] += src_edge.txn_count + dst_edge.txn_count
                        data["shared_counterparties"].append(cp_key)
                        if src_edge.first_seen_at and (
                            data["first_seen"] is None
                            or src_edge.first_seen_at < data["first_seen"]
                        ):
                            data["first_seen"] = src_edge.first_seen_at
                        if dst_edge.last_seen_at and (
                            data["last_seen"] is None
                            or dst_edge.last_seen_at > data["last_seen"]
                        ):
                            data["last_seen"] = dst_edge.last_seen_at
                    else:
                        first_seen = min(
                            filter(None, [src_edge.first_seen_at, dst_edge.first_seen_at]),
                            default=None,
                        )
                        last_seen = max(
                            filter(None, [src_edge.last_seen_at, dst_edge.last_seen_at]),
                            default=None,
                        )
                        G.add_edge(
                            src_id,
                            dst_id,
                            txn_count=src_edge.txn_count + dst_edge.txn_count,
                            total_amount=0.0,
                            first_seen=first_seen,
                            last_seen=last_seen,
                            shared_counterparties=[cp_key],
                        )

    return G


def get_account_subgraph(
    account_id: int, session: Any, hops: int = 2
) -> nx.DiGraph:
    """
    Extract a multi-hop neighborhood subgraph around account_id.
    Returns the induced subgraph within `hops` distance.
    """
    G = build_transaction_graph(session)

    if account_id not in G:
        return nx.DiGraph()

    # BFS to find all nodes within `hops` distance (undirected traversal)
    undirected = G.to_undirected()
    reachable = nx.single_source_shortest_path_length(undirected, account_id, cutoff=hops)
    sub_nodes = set(reachable.keys())
    return G.subgraph(sub_nodes).copy()
