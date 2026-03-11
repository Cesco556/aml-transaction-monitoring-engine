"""Graph export for visualization: D3.js and Cytoscape.js formats."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import networkx as nx


def _serialize_value(v: Any) -> Any:
    """Convert non-JSON-serializable types."""
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_serialize_value(i) for i in v]
    return v


def export_d3_json(
    graph: nx.DiGraph,
    community_filter: int | None = None,
    communities: dict[int, list[int]] | None = None,
) -> dict:
    """
    Export graph to D3.js force-directed format.

    Format:
        {
            "nodes": [{"id": 1, "account_id": 1, ...}, ...],
            "links": [{"source": 1, "target": 2, ...}, ...]
        }
    """
    # Determine which nodes to include
    include_nodes: set[int] | None = None
    if community_filter is not None and communities is not None:
        include_nodes = set(communities.get(community_filter, []))

    nodes = []
    for node_id, data in graph.nodes(data=True):
        if include_nodes is not None and node_id not in include_nodes:
            continue
        node_dict = {"id": node_id}
        for k, v in data.items():
            node_dict[k] = _serialize_value(v)
        # Add community ID if available
        if communities:
            for cid, members in communities.items():
                if node_id in members:
                    node_dict["community"] = cid
                    break
        nodes.append(node_dict)

    node_ids = {n["id"] for n in nodes}
    links = []
    for src, dst, data in graph.edges(data=True):
        if src not in node_ids or dst not in node_ids:
            continue
        link_dict = {"source": src, "target": dst}
        for k, v in data.items():
            link_dict[k] = _serialize_value(v)
        links.append(link_dict)

    return {"nodes": nodes, "links": links}


def export_cytoscape(
    graph: nx.DiGraph,
    community_filter: int | None = None,
    communities: dict[int, list[int]] | None = None,
) -> dict:
    """
    Export graph to Cytoscape.js format.

    Format:
        {
            "elements": {
                "nodes": [{"data": {"id": "1", ...}}, ...],
                "edges": [{"data": {"source": "1", "target": "2", ...}}, ...]
            }
        }
    """
    include_nodes: set[int] | None = None
    if community_filter is not None and communities is not None:
        include_nodes = set(communities.get(community_filter, []))

    cy_nodes = []
    for node_id, data in graph.nodes(data=True):
        if include_nodes is not None and node_id not in include_nodes:
            continue
        node_data: dict[str, Any] = {"id": str(node_id)}
        for k, v in data.items():
            node_data[k] = _serialize_value(v)
        if communities:
            for cid, members in communities.items():
                if node_id in members:
                    node_data["community"] = cid
                    break
        cy_nodes.append({"data": node_data})

    node_ids = {n["data"]["id"] for n in cy_nodes}
    cy_edges = []
    for src, dst, data in graph.edges(data=True):
        if str(src) not in node_ids or str(dst) not in node_ids:
            continue
        edge_data: dict[str, Any] = {
            "id": f"{src}-{dst}",
            "source": str(src),
            "target": str(dst),
        }
        for k, v in data.items():
            edge_data[k] = _serialize_value(v)
        cy_edges.append({"data": edge_data})

    return {"elements": {"nodes": cy_nodes, "edges": cy_edges}}
