"""Community detection: Louvain and label propagation for AML network analysis."""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx


@dataclass
class Community:
    """A detected community with risk metrics."""

    id: int
    accounts: list[int] = field(default_factory=list)
    total_alerts: int = 0
    alert_ratio: float = 0.0
    total_volume: float = 0.0
    risk_score: float = 0.0


def detect_communities(
    graph: nx.DiGraph, method: str = "louvain"
) -> dict[int, list[int]]:
    """
    Detect communities in the graph.

    Args:
        graph: Directed transaction graph.
        method: "louvain" or "label_propagation".

    Returns:
        dict mapping community_id -> list of account_ids.
    """
    if len(graph.nodes) == 0:
        return {}

    undirected = graph.to_undirected()

    if method == "louvain":
        partition = nx.community.louvain_communities(undirected, seed=42)
    elif method == "label_propagation":
        partition = nx.community.label_propagation_communities(undirected)
    else:
        raise ValueError(f"Unknown community detection method: {method}")

    communities: dict[int, list[int]] = {}
    for idx, community_set in enumerate(partition):
        communities[idx] = sorted(community_set)

    return communities


def get_suspicious_communities(
    graph: nx.DiGraph,
    communities: dict[int, list[int]],
    min_alert_ratio: float = 0.3,
) -> list[Community]:
    """
    Identify suspicious communities based on alert ratio.

    A community is suspicious if the ratio of accounts with alerts
    to total accounts exceeds min_alert_ratio.

    Args:
        graph: Directed transaction graph with node attributes.
        communities: Output of detect_communities().
        min_alert_ratio: Minimum alert ratio to flag as suspicious.

    Returns:
        List of Community objects sorted by risk_score descending.
    """
    suspicious: list[Community] = []

    for cid, account_ids in communities.items():
        if not account_ids:
            continue

        total_alerts = 0
        accounts_with_alerts = 0
        total_volume = 0.0

        for aid in account_ids:
            node_data = graph.nodes.get(aid, {})
            alerts = node_data.get("alert_count", 0)
            total_alerts += alerts
            if alerts > 0:
                accounts_with_alerts += 1
            total_volume += node_data.get("total_txn_volume", 0.0)

        alert_ratio = accounts_with_alerts / len(account_ids) if account_ids else 0.0

        if alert_ratio >= min_alert_ratio:
            # Risk score: weighted combination of alert ratio, total alerts, and community size
            risk_score = round(
                (alert_ratio * 50)
                + (min(total_alerts, 20) * 2)
                + (min(len(account_ids), 10) * 1),
                2,
            )

            suspicious.append(
                Community(
                    id=cid,
                    accounts=account_ids,
                    total_alerts=total_alerts,
                    alert_ratio=round(alert_ratio, 4),
                    total_volume=round(total_volume, 2),
                    risk_score=risk_score,
                )
            )

    suspicious.sort(key=lambda c: c.risk_score, reverse=True)
    return suspicious
