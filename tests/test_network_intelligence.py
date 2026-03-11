"""Tests for Phase 7: Network Intelligence — graph analysis, communities, paths, ownership, export, API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import networkx as nx
import pytest
from fastapi.testclient import TestClient

from aml_monitoring.db import init_db, session_scope
from aml_monitoring.models import (
    Account,
    Alert,
    Base,
    Customer,
    RelationshipEdge,
    Transaction,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _setup_db(tmp_path):
    """Initialize a fresh in-memory DB for each test."""
    db_url = f"sqlite:///{tmp_path}/test.db"
    init_db(db_url, echo=False)
    yield


def _seed_ring_network(session) -> dict[str, list[int]]:
    """
    Seed a ring-shaped network. Returns dict of IDs (not ORM objects).

    - 4 customers, 4 accounts
    - Accounts 1,2,3 share counterparties CP-A and CP-B (ring)
    - Account 4 is isolated (different counterparty CP-Z)
    - Accounts 1 and 2 have alerts
    """
    now = datetime.now(UTC)
    yesterday = now - timedelta(days=1)

    c1 = Customer(name="Alice", country="US", base_risk=10)
    c2 = Customer(name="Bob", country="GB", base_risk=20)
    c3 = Customer(name="Charlie", country="US", base_risk=15)
    c4 = Customer(name="Diana", country="DE", base_risk=5)
    session.add_all([c1, c2, c3, c4])
    session.flush()

    a1 = Account(customer_id=c1.id, iban_or_acct="ACCT001")
    a2 = Account(customer_id=c2.id, iban_or_acct="ACCT002")
    a3 = Account(customer_id=c3.id, iban_or_acct="ACCT003")
    a4 = Account(customer_id=c4.id, iban_or_acct="ACCT004")
    session.add_all([a1, a2, a3, a4])
    session.flush()

    txns = [
        Transaction(account_id=a1.id, ts=yesterday, amount=1000, currency="USD",
                    counterparty="cp-a", direction="out"),
        Transaction(account_id=a1.id, ts=yesterday, amount=2000, currency="USD",
                    counterparty="cp-b", direction="out"),
        Transaction(account_id=a2.id, ts=yesterday, amount=1500, currency="USD",
                    counterparty="cp-a", direction="out"),
        Transaction(account_id=a2.id, ts=yesterday, amount=500, currency="USD",
                    counterparty="cp-b", direction="in"),
        Transaction(account_id=a3.id, ts=yesterday, amount=3000, currency="USD",
                    counterparty="cp-a", direction="out"),
        Transaction(account_id=a3.id, ts=yesterday, amount=800, currency="USD",
                    counterparty="cp-b", direction="out"),
        Transaction(account_id=a4.id, ts=yesterday, amount=100, currency="USD",
                    counterparty="cp-z", direction="out"),
    ]
    session.add_all(txns)
    session.flush()

    alert1 = Alert(transaction_id=txns[0].id, rule_id="TEST", severity="high",
                   score=80, reason="suspicious")
    alert2 = Alert(transaction_id=txns[2].id, rule_id="TEST", severity="medium",
                   score=60, reason="suspicious")
    session.add_all([alert1, alert2])
    session.flush()

    edges = [
        RelationshipEdge(src_type="account", src_id=a1.id, dst_type="counterparty",
                         dst_key="cp-a", first_seen_at=yesterday, last_seen_at=now, txn_count=1),
        RelationshipEdge(src_type="account", src_id=a1.id, dst_type="counterparty",
                         dst_key="cp-b", first_seen_at=yesterday, last_seen_at=now, txn_count=1),
        RelationshipEdge(src_type="account", src_id=a2.id, dst_type="counterparty",
                         dst_key="cp-a", first_seen_at=yesterday, last_seen_at=now, txn_count=1),
        RelationshipEdge(src_type="account", src_id=a2.id, dst_type="counterparty",
                         dst_key="cp-b", first_seen_at=yesterday, last_seen_at=now, txn_count=1),
        RelationshipEdge(src_type="account", src_id=a3.id, dst_type="counterparty",
                         dst_key="cp-a", first_seen_at=yesterday, last_seen_at=now, txn_count=1),
        RelationshipEdge(src_type="account", src_id=a3.id, dst_type="counterparty",
                         dst_key="cp-b", first_seen_at=yesterday, last_seen_at=now, txn_count=1),
        RelationshipEdge(src_type="account", src_id=a4.id, dst_type="counterparty",
                         dst_key="cp-z", first_seen_at=yesterday, last_seen_at=now, txn_count=1),
    ]
    session.add_all(edges)
    session.flush()

    return {
        "account_ids": [a1.id, a2.id, a3.id, a4.id],
        "customer_ids": [c1.id, c2.id, c3.id, c4.id],
    }


# ---------------------------------------------------------------------------
# Graph Analysis Tests
# ---------------------------------------------------------------------------

class TestGraphAnalysis:
    def test_build_transaction_graph(self):
        from aml_monitoring.network.graph import build_transaction_graph

        with session_scope() as session:
            ids = _seed_ring_network(session)
            graph = build_transaction_graph(session)

            assert len(graph.nodes) == 4
            assert graph.has_node(ids["account_ids"][0])
            assert graph.has_node(ids["account_ids"][3])

    def test_graph_node_attributes(self):
        from aml_monitoring.network.graph import build_transaction_graph

        with session_scope() as session:
            ids = _seed_ring_network(session)
            graph = build_transaction_graph(session)

            a1_id = ids["account_ids"][0]
            node = graph.nodes[a1_id]
            assert node["customer_name"] == "Alice"
            assert node["country"] == "US"
            assert node["total_txn_volume"] > 0
            assert node["alert_count"] >= 1

    def test_graph_edges_between_ring_accounts(self):
        from aml_monitoring.network.graph import build_transaction_graph

        with session_scope() as session:
            ids = _seed_ring_network(session)
            graph = build_transaction_graph(session)

            a1, a2, a3, a4 = ids["account_ids"]
            assert graph.has_edge(a1, a2) or graph.has_edge(a2, a1)
            assert graph.has_edge(a1, a3) or graph.has_edge(a3, a1)
            assert not graph.has_edge(a4, a1)
            assert not graph.has_edge(a1, a4)

    def test_graph_edge_attributes(self):
        from aml_monitoring.network.graph import build_transaction_graph

        with session_scope() as session:
            ids = _seed_ring_network(session)
            graph = build_transaction_graph(session)

            a1, a2 = ids["account_ids"][0], ids["account_ids"][1]
            if graph.has_edge(a1, a2):
                edge = graph[a1][a2]
            else:
                edge = graph[a2][a1]

            assert "txn_count" in edge
            assert edge["txn_count"] > 0
            assert "shared_counterparties" in edge
            assert "first_seen" in edge
            assert "last_seen" in edge

    def test_get_account_subgraph(self):
        from aml_monitoring.network.graph import get_account_subgraph

        with session_scope() as session:
            ids = _seed_ring_network(session)
            sub = get_account_subgraph(ids["account_ids"][0], session, hops=1)

            assert ids["account_ids"][0] in sub.nodes
            assert ids["account_ids"][3] not in sub.nodes

    def test_get_account_subgraph_missing_account(self):
        from aml_monitoring.network.graph import get_account_subgraph

        with session_scope() as session:
            _seed_ring_network(session)
            sub = get_account_subgraph(99999, session, hops=2)
            assert len(sub.nodes) == 0

    def test_empty_graph(self):
        from aml_monitoring.network.graph import build_transaction_graph

        with session_scope() as session:
            graph = build_transaction_graph(session)
            assert len(graph.nodes) == 0
            assert len(graph.edges) == 0


# ---------------------------------------------------------------------------
# Community Detection Tests
# ---------------------------------------------------------------------------

class TestCommunityDetection:
    def test_louvain_detection(self):
        from aml_monitoring.network.communities import detect_communities
        from aml_monitoring.network.graph import build_transaction_graph

        with session_scope() as session:
            ids = _seed_ring_network(session)
            graph = build_transaction_graph(session)

        communities = detect_communities(graph, method="louvain")
        assert len(communities) >= 1

        all_accounts = set()
        for members in communities.values():
            all_accounts.update(members)
        for aid in ids["account_ids"]:
            assert aid in all_accounts

    def test_label_propagation_detection(self):
        from aml_monitoring.network.communities import detect_communities
        from aml_monitoring.network.graph import build_transaction_graph

        with session_scope() as session:
            _seed_ring_network(session)
            graph = build_transaction_graph(session)

        communities = detect_communities(graph, method="label_propagation")
        assert len(communities) >= 1

    def test_invalid_method(self):
        from aml_monitoring.network.communities import detect_communities

        G = nx.DiGraph()
        G.add_node(1)
        with pytest.raises(ValueError, match="Unknown community detection method"):
            detect_communities(G, method="invalid")

    def test_empty_graph_communities(self):
        from aml_monitoring.network.communities import detect_communities

        G = nx.DiGraph()
        communities = detect_communities(G)
        assert communities == {}

    def test_suspicious_communities(self):
        from aml_monitoring.network.communities import (
            detect_communities,
            get_suspicious_communities,
        )
        from aml_monitoring.network.graph import build_transaction_graph

        with session_scope() as session:
            _seed_ring_network(session)
            graph = build_transaction_graph(session)

        communities = detect_communities(graph)
        suspicious = get_suspicious_communities(graph, communities, min_alert_ratio=0.0)
        assert len(suspicious) >= 1
        for c in suspicious:
            assert c.risk_score > 0
            assert len(c.accounts) > 0

    def test_suspicious_communities_high_threshold(self):
        from aml_monitoring.network.communities import (
            detect_communities,
            get_suspicious_communities,
        )
        from aml_monitoring.network.graph import build_transaction_graph

        with session_scope() as session:
            _seed_ring_network(session)
            graph = build_transaction_graph(session)

        communities = detect_communities(graph)
        suspicious = get_suspicious_communities(graph, communities, min_alert_ratio=1.0)
        assert isinstance(suspicious, list)


# ---------------------------------------------------------------------------
# Path Analysis Tests
# ---------------------------------------------------------------------------

class TestPathAnalysis:
    def test_shortest_path(self):
        from aml_monitoring.network.graph import build_transaction_graph
        from aml_monitoring.network.paths import find_shortest_path

        with session_scope() as session:
            ids = _seed_ring_network(session)
            graph = build_transaction_graph(session)

        a1, a3 = ids["account_ids"][0], ids["account_ids"][2]
        path = find_shortest_path(graph, a1, a3)
        assert len(path) >= 2
        assert path[0] == a1
        assert path[-1] == a3

    def test_shortest_path_no_path(self):
        from aml_monitoring.network.graph import build_transaction_graph
        from aml_monitoring.network.paths import find_shortest_path

        with session_scope() as session:
            ids = _seed_ring_network(session)
            graph = build_transaction_graph(session)

        a1, a4 = ids["account_ids"][0], ids["account_ids"][3]
        path = find_shortest_path(graph, a1, a4)
        assert path == []

    def test_shortest_path_missing_node(self):
        from aml_monitoring.network.paths import find_shortest_path

        G = nx.DiGraph()
        G.add_node(1)
        assert find_shortest_path(G, 1, 999) == []

    def test_find_all_paths(self):
        from aml_monitoring.network.graph import build_transaction_graph
        from aml_monitoring.network.paths import find_all_paths

        with session_scope() as session:
            ids = _seed_ring_network(session)
            graph = build_transaction_graph(session)

        a1, a3 = ids["account_ids"][0], ids["account_ids"][2]
        paths = find_all_paths(graph, a1, a3, max_hops=4)
        assert len(paths) >= 1
        for p in paths:
            assert p[0] == a1
            assert p[-1] == a3

    def test_find_all_paths_no_path(self):
        from aml_monitoring.network.paths import find_all_paths

        G = nx.DiGraph()
        G.add_nodes_from([1, 2])
        assert find_all_paths(G, 1, 2) == []

    def test_money_flow_trace(self):
        from aml_monitoring.network.paths import flow_tree_to_dict, trace_money_flow

        with session_scope() as session:
            ids = _seed_ring_network(session)
            flow = trace_money_flow(session, ids["account_ids"][0], direction="out")

            assert flow.account_id == ids["account_ids"][0]
            flow_dict = flow_tree_to_dict(flow)
            assert "account_id" in flow_dict
            assert "children" in flow_dict
            assert isinstance(flow_dict["children"], list)

    def test_money_flow_inbound(self):
        from aml_monitoring.network.paths import trace_money_flow

        with session_scope() as session:
            ids = _seed_ring_network(session)
            flow = trace_money_flow(session, ids["account_ids"][1], direction="in")
            assert flow.account_id == ids["account_ids"][1]


# ---------------------------------------------------------------------------
# Ownership Analysis Tests
# ---------------------------------------------------------------------------

class TestOwnershipAnalysis:
    def test_find_common_owners_shared_customer(self):
        from aml_monitoring.network.ownership import find_common_owners

        with session_scope() as session:
            c = Customer(name="Shared Owner", country="US", base_risk=10)
            session.add(c)
            session.flush()
            a1 = Account(customer_id=c.id, iban_or_acct="OWN001")
            a2 = Account(customer_id=c.id, iban_or_acct="OWN002")
            session.add_all([a1, a2])
            session.flush()

            owners = find_common_owners(session, [a1.id, a2.id])
            assert len(owners) == 1
            assert owners[0].customer_name == "Shared Owner"
            assert set(owners[0].account_ids) == {a1.id, a2.id}

    def test_find_common_owners_no_overlap(self):
        from aml_monitoring.network.ownership import find_common_owners

        with session_scope() as session:
            ids = _seed_ring_network(session)
            owners = find_common_owners(
                session, [ids["account_ids"][0], ids["account_ids"][1]]
            )
            assert len(owners) == 0

    def test_get_ownership_chain(self):
        from aml_monitoring.network.ownership import get_ownership_chain

        with session_scope() as session:
            ids = _seed_ring_network(session)
            chain = get_ownership_chain(session, ids["account_ids"][0])

            assert len(chain) >= 1
            assert chain[0].link_type == "direct"
            assert chain[0].customer_name == "Alice"

    def test_get_ownership_chain_with_counterparty_pattern(self):
        from aml_monitoring.network.ownership import get_ownership_chain

        with session_scope() as session:
            ids = _seed_ring_network(session)
            chain = get_ownership_chain(session, ids["account_ids"][0])

            cp_links = [l for l in chain if l.link_type == "counterparty_pattern"]
            assert len(cp_links) >= 1
            for link in cp_links:
                assert len(link.shared_counterparties) >= 2

    def test_get_ownership_chain_missing_account(self):
        from aml_monitoring.network.ownership import get_ownership_chain

        with session_scope() as session:
            _seed_ring_network(session)
            chain = get_ownership_chain(session, 99999)
            assert chain == []


# ---------------------------------------------------------------------------
# Graph Export Tests
# ---------------------------------------------------------------------------

class TestGraphExport:
    def test_d3_export(self):
        from aml_monitoring.network.export import export_d3_json
        from aml_monitoring.network.graph import build_transaction_graph

        with session_scope() as session:
            _seed_ring_network(session)
            graph = build_transaction_graph(session)

        result = export_d3_json(graph)
        assert "nodes" in result
        assert "links" in result
        assert len(result["nodes"]) == 4
        for node in result["nodes"]:
            assert "id" in node
            assert "customer_name" in node

    def test_d3_export_with_communities(self):
        from aml_monitoring.network.communities import detect_communities
        from aml_monitoring.network.export import export_d3_json
        from aml_monitoring.network.graph import build_transaction_graph

        with session_scope() as session:
            _seed_ring_network(session)
            graph = build_transaction_graph(session)

        communities = detect_communities(graph)
        result = export_d3_json(graph, communities=communities)
        has_community = any("community" in n for n in result["nodes"])
        assert has_community

    def test_d3_export_community_filter(self):
        from aml_monitoring.network.communities import detect_communities
        from aml_monitoring.network.export import export_d3_json
        from aml_monitoring.network.graph import build_transaction_graph

        with session_scope() as session:
            _seed_ring_network(session)
            graph = build_transaction_graph(session)

        communities = detect_communities(graph)
        if communities:
            first_cid = next(iter(communities))
            result = export_d3_json(
                graph, community_filter=first_cid, communities=communities
            )
            node_ids = {n["id"] for n in result["nodes"]}
            assert node_ids == set(communities[first_cid])

    def test_cytoscape_export(self):
        from aml_monitoring.network.export import export_cytoscape
        from aml_monitoring.network.graph import build_transaction_graph

        with session_scope() as session:
            _seed_ring_network(session)
            graph = build_transaction_graph(session)

        result = export_cytoscape(graph)
        assert "elements" in result
        assert "nodes" in result["elements"]
        assert "edges" in result["elements"]
        assert len(result["elements"]["nodes"]) == 4
        for node in result["elements"]["nodes"]:
            assert "data" in node
            assert "id" in node["data"]
            assert isinstance(node["data"]["id"], str)

    def test_cytoscape_edge_format(self):
        from aml_monitoring.network.export import export_cytoscape
        from aml_monitoring.network.graph import build_transaction_graph

        with session_scope() as session:
            _seed_ring_network(session)
            graph = build_transaction_graph(session)

        result = export_cytoscape(graph)
        for edge in result["elements"]["edges"]:
            assert "data" in edge
            assert "source" in edge["data"]
            assert "target" in edge["data"]
            assert isinstance(edge["data"]["source"], str)

    def test_empty_graph_export(self):
        from aml_monitoring.network.export import export_cytoscape, export_d3_json

        G = nx.DiGraph()
        d3 = export_d3_json(G)
        assert d3 == {"nodes": [], "links": []}

        cy = export_cytoscape(G)
        assert cy == {"elements": {"nodes": [], "edges": []}}


# ---------------------------------------------------------------------------
# API Endpoint Tests
# ---------------------------------------------------------------------------

class TestNetworkAPI:
    @pytest.fixture
    def client(self):
        from aml_monitoring.api import app
        return TestClient(app)

    def test_network_graph_endpoint(self, client):
        with session_scope() as session:
            ids = _seed_ring_network(session)
        a1_id = ids["account_ids"][0]

        resp = client.get(f"/network/graph?account_id={a1_id}&hops=2")
        assert resp.status_code == 200
        body = resp.json()
        assert "nodes" in body
        assert "links" in body

    def test_network_graph_full(self, client):
        with session_scope() as session:
            _seed_ring_network(session)

        resp = client.get("/network/graph")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["nodes"]) >= 1

    def test_network_communities_endpoint(self, client):
        with session_scope() as session:
            _seed_ring_network(session)

        resp = client.get("/network/communities")
        assert resp.status_code == 200
        body = resp.json()
        assert "total_communities" in body
        assert "suspicious_count" in body
        assert "communities" in body

    def test_network_communities_label_propagation(self, client):
        with session_scope() as session:
            _seed_ring_network(session)

        resp = client.get("/network/communities?method=label_propagation&min_alert_ratio=0")
        assert resp.status_code == 200

    def test_network_path_endpoint(self, client):
        with session_scope() as session:
            ids = _seed_ring_network(session)
        a1_id, a3_id = ids["account_ids"][0], ids["account_ids"][2]

        resp = client.get(f"/network/path?from={a1_id}&to={a3_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert "shortest_path" in body
        assert "all_paths" in body
        assert "path_count" in body

    def test_network_flow_endpoint(self, client):
        with session_scope() as session:
            ids = _seed_ring_network(session)
        a1_id = ids["account_ids"][0]

        resp = client.get(f"/network/flow?account_id={a1_id}&direction=out&depth=2")
        assert resp.status_code == 200
        body = resp.json()
        assert "flow" in body
        assert body["flow"]["account_id"] == a1_id

    def test_existing_network_account_endpoint(self, client):
        with session_scope() as session:
            ids = _seed_ring_network(session)
        a1_id = ids["account_ids"][0]

        resp = client.get(f"/network/account/{a1_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert "edges" in body
        assert "ring_signal" in body


# ---------------------------------------------------------------------------
# Ring Structure Tests
# ---------------------------------------------------------------------------

class TestRingStructures:
    def test_three_account_ring(self):
        from aml_monitoring.network.graph import build_transaction_graph

        with session_scope() as session:
            ids = _seed_ring_network(session)
            graph = build_transaction_graph(session)

        a1, a2, a3 = ids["account_ids"][:3]
        undirected = graph.to_undirected()
        assert nx.has_path(undirected, a1, a2)
        assert nx.has_path(undirected, a2, a3)
        assert nx.has_path(undirected, a1, a3)

    def test_ring_community_detected(self):
        from aml_monitoring.network.communities import detect_communities
        from aml_monitoring.network.graph import build_transaction_graph

        with session_scope() as session:
            ids = _seed_ring_network(session)
            graph = build_transaction_graph(session)

        communities = detect_communities(graph)
        ring_ids = set(ids["account_ids"][:3])

        # Ring accounts should be in the same community or at least connected
        for cid, members in communities.items():
            if ring_ids.issubset(set(members)):
                break
        else:
            undirected = graph.to_undirected()
            for a in ring_ids:
                for b in ring_ids:
                    if a != b:
                        assert nx.has_path(undirected, a, b)

    def test_isolated_account_separate(self):
        from aml_monitoring.network.graph import build_transaction_graph
        from aml_monitoring.network.paths import find_shortest_path

        with session_scope() as session:
            ids = _seed_ring_network(session)
            graph = build_transaction_graph(session)

        a1_id, a4_id = ids["account_ids"][0], ids["account_ids"][3]
        path = find_shortest_path(graph, a1_id, a4_id)
        assert path == []
