"""FastAPI app: score single transaction, fetch alerts."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.openapi.utils import get_openapi
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from aml_monitoring import ENGINE_VERSION, RULES_VERSION

_STARTUP_TIME: float = time.time()
from aml_monitoring.audit_context import get_correlation_id, set_audit_context
from aml_monitoring.auth import require_api_key_write
from aml_monitoring.cases_api import cases_router
from aml_monitoring.reports_api import reports_router
from aml_monitoring.config import get_config, get_config_hash
from aml_monitoring.db import init_db, session_scope
from aml_monitoring.models import Alert, AuditLog, Transaction
from aml_monitoring.rules import get_all_rules
from aml_monitoring.rules.base import RuleContext
from aml_monitoring.schemas import (
    ALERT_DISPOSITION_VALUES,
    ALERT_STATUS_VALUES,
    AlertResponse,
    RuleHit,
    RuleResult,
    ScoreRequest,
    ScoreResponse,
    TransactionCreate,
    TransactionResponse,
)
from aml_monitoring.scoring import compute_transaction_risk
from aml_monitoring.security import setup_security


def _build_context_for_score(t: TransactionCreate, session: Any) -> RuleContext | None:
    """Build RuleContext if we have account_id in DB (for full rule run)."""
    from sqlalchemy import select

    from aml_monitoring.models import Account

    acct = session.execute(select(Account).where(Account.id == t.account_id)).scalar_one_or_none()
    if not acct:
        return None
    return RuleContext(
        transaction_id=0,
        account_id=acct.id,
        customer_id=acct.customer_id,
        ts=t.ts,
        amount=t.amount,
        currency=t.currency,
        merchant=t.merchant,
        counterparty=t.counterparty,
        country=t.country,
        channel=t.channel,
        direction=t.direction,
        session=session,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    db_url = config.get("database", {}).get("url", "sqlite:///./data/aml.db")
    echo = config.get("database", {}).get("echo", False)
    init_db(db_url, echo=echo)
    yield
    # no cleanup needed for SQLite


app = FastAPI(
    title="AML Monitoring API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


class AuditContextMiddleware(BaseHTTPMiddleware):
    """Set correlation_id per request; echo X-Correlation-ID in response.
    Actor is NOT set from X-Actor (ignored); for protected routes it is set by require_api_key from API key identity; for GET routes it remains anonymous.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        set_audit_context(correlation_id, "anonymous")
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response


app.add_middleware(AuditContextMiddleware)

# Security middleware (rate limiting, CORS, headers, request size)
setup_security(app)

app.include_router(cases_router)
app.include_router(reports_router)

# WebSocket endpoint for real-time alert notifications
from aml_monitoring.streaming.websocket import websocket_alerts_endpoint

app.websocket("/ws/alerts")(websocket_alerts_endpoint)


# ---------------------------------------------------------------------------
# Custom OpenAPI schema with security definitions
# ---------------------------------------------------------------------------

def custom_openapi() -> dict[str, Any]:
    """Generate OpenAPI schema with API key security scheme."""
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description="AML Transaction Monitoring API. "
        "Write endpoints require X-API-Key authentication.",
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "API key for authentication. "
            "Write operations require read_write scope.",
        }
    }
    # Apply security globally (individual endpoints can override)
    openapi_schema["security"] = [{"ApiKeyAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> Any:
    """Catch unhandled exceptions; return generic 500 without leaking internals."""
    from fastapi.responses import JSONResponse

    # Re-raise HTTPException so FastAPI handles it normally
    if isinstance(exc, HTTPException):
        raise exc
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/network/account/{account_id}")
def get_network_account(account_id: int) -> dict[str, Any]:
    """Return relationship edges and ring metrics for an account (investigator view)."""
    from sqlalchemy import select

    from aml_monitoring.models import RelationshipEdge
    from aml_monitoring.network.metrics import ring_signal

    with session_scope() as session:
        edges = list(
            session.execute(
                select(RelationshipEdge)
                .where(RelationshipEdge.src_type == "account")
                .where(RelationshipEdge.src_id == account_id)
                .order_by(RelationshipEdge.dst_type, RelationshipEdge.dst_key)
            )
            .scalars()
            .all()
        )
        edge_list = [
            {
                "id": e.id,
                "src_type": e.src_type,
                "src_id": e.src_id,
                "dst_type": e.dst_type,
                "dst_key": e.dst_key,
                "txn_count": e.txn_count,
                "first_seen_at": e.first_seen_at.isoformat() if e.first_seen_at else None,
                "last_seen_at": e.last_seen_at.isoformat() if e.last_seen_at else None,
            }
            for e in edges
        ]
        ring = ring_signal(account_id, session, lookback_days=30)
        return {
            "account_id": account_id,
            "edges": edge_list,
            "edge_count": len(edge_list),
            "ring_signal": {
                "overlap_count": ring.overlap_count,
                "linked_accounts": ring.linked_accounts,
                "shared_counterparties": ring.shared_counterparties,
                "degree": ring.degree,
            },
        }


@app.get("/network/graph")
def get_network_graph(
    account_id: int | None = Query(None, description="Center account ID"),
    hops: int = Query(2, ge=1, le=5, description="Number of hops from account"),
) -> dict[str, Any]:
    """Get subgraph around an account in D3.js format."""
    from aml_monitoring.network.communities import detect_communities
    from aml_monitoring.network.export import export_d3_json
    from aml_monitoring.network.graph import build_transaction_graph, get_account_subgraph

    with session_scope() as session:
        if account_id is not None:
            graph = get_account_subgraph(account_id, session, hops=hops)
        else:
            graph = build_transaction_graph(session)

        communities = detect_communities(graph) if len(graph.nodes) > 0 else {}
        return export_d3_json(graph, communities=communities)


@app.get("/network/communities")
def get_network_communities(
    method: str = Query("louvain", description="louvain or label_propagation"),
    min_alert_ratio: float = Query(0.3, ge=0.0, le=1.0),
) -> dict[str, Any]:
    """Detect communities and return with risk scores."""
    from aml_monitoring.network.communities import detect_communities, get_suspicious_communities
    from aml_monitoring.network.graph import build_transaction_graph

    with session_scope() as session:
        graph = build_transaction_graph(session)
        communities = detect_communities(graph, method=method)
        suspicious = get_suspicious_communities(graph, communities, min_alert_ratio=min_alert_ratio)

        return {
            "total_communities": len(communities),
            "suspicious_count": len(suspicious),
            "communities": [
                {
                    "id": c.id,
                    "accounts": c.accounts,
                    "total_alerts": c.total_alerts,
                    "alert_ratio": c.alert_ratio,
                    "total_volume": c.total_volume,
                    "risk_score": c.risk_score,
                }
                for c in suspicious
            ],
        }


@app.get("/network/path")
def get_network_path(
    source: int = Query(..., alias="from", description="Source account ID"),
    target: int = Query(..., alias="to", description="Target account ID"),
    max_hops: int = Query(4, ge=1, le=10),
) -> dict[str, Any]:
    """Find paths between two accounts."""
    from aml_monitoring.network.graph import build_transaction_graph
    from aml_monitoring.network.paths import find_all_paths, find_shortest_path

    with session_scope() as session:
        graph = build_transaction_graph(session)
        shortest = find_shortest_path(graph, source, target)
        all_paths = find_all_paths(graph, source, target, max_hops=max_hops)

        return {
            "source": source,
            "target": target,
            "shortest_path": shortest,
            "all_paths": all_paths,
            "path_count": len(all_paths),
        }


@app.get("/network/flow")
def get_network_flow(
    account_id: int = Query(..., description="Account ID to trace"),
    direction: str = Query("out", description="out or in"),
    depth: int = Query(3, ge=1, le=5),
) -> dict[str, Any]:
    """Trace money flow from/to an account."""
    from aml_monitoring.network.paths import flow_tree_to_dict, trace_money_flow

    with session_scope() as session:
        flow = trace_money_flow(
            session, account_id, direction=direction, max_depth=depth
        )
        return {
            "account_id": account_id,
            "direction": direction,
            "max_depth": depth,
            "flow": flow_tree_to_dict(flow),
        }


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness and version; db_status indicates DB connectivity."""
    from sqlalchemy import text

    from aml_monitoring.db import get_engine

    db_status = "unknown"
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"
    return {
        "status": "ok",
        "engine_version": ENGINE_VERSION,
        "rules_version": RULES_VERSION,
        "db_status": db_status,
    }


@app.get("/ready")
def readiness() -> dict[str, Any]:
    """Readiness check: DB connectivity + ML model availability."""
    from pathlib import Path

    from sqlalchemy import text

    from aml_monitoring.db import get_engine

    checks: dict[str, str] = {}

    # DB connectivity
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"

    # ML model availability
    model_path = Path("models/anomaly_model.joblib")
    checks["ml_model"] = "ok" if model_path.exists() else "unavailable"

    ready = checks["database"] == "ok"
    status_code = 200 if ready else 503
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status_code,
        content={"ready": ready, "checks": checks},
    )


@app.get("/metrics")
def metrics() -> dict[str, Any]:
    """Basic operational metrics: counts and uptime."""
    from sqlalchemy import func, select

    from aml_monitoring.db import get_engine
    from aml_monitoring.models import Alert, Case, Transaction

    uptime_seconds = round(time.time() - _STARTUP_TIME, 2)
    counts: dict[str, int] = {}

    try:
        engine = get_engine()
        with engine.connect() as conn:
            for label, model in [
                ("transactions", Transaction),
                ("alerts", Alert),
                ("cases", Case),
            ]:
                result = conn.execute(select(func.count()).select_from(model.__table__))
                counts[label] = result.scalar() or 0
    except Exception:
        counts = {"transactions": -1, "alerts": -1, "cases": -1}

    return {
        "uptime_seconds": uptime_seconds,
        "engine_version": ENGINE_VERSION,
        "rules_version": RULES_VERSION,
        "counts": counts,
    }


@app.post("/score", response_model=ScoreResponse)
def score_transaction(body: ScoreRequest) -> ScoreResponse:
    """Score a single transaction (uses DB for velocity/geo/structuring if account exists)."""
    config = get_config()
    rules = get_all_rules(config)
    scoring_cfg = config.get("scoring", {})
    base_risk = float(scoring_cfg.get("base_risk_per_customer", 10))
    max_score = float(scoring_cfg.get("max_score", 100))
    thresholds = scoring_cfg.get("thresholds", {})
    low_t = float(thresholds.get("low", 33))
    med_t = float(thresholds.get("medium", 66))

    t = body.transaction
    rule_results: list[RuleResult] = []
    ctx = None
    with session_scope() as session:
        ctx = _build_context_for_score(t, session)

    if ctx is None:
        # Stateless only: high value, sanctions, high risk country
        from types import SimpleNamespace

        stateless_ctx = RuleContext(
            transaction_id=0,
            account_id=t.account_id,
            customer_id=0,
            ts=t.ts,
            amount=t.amount,
            currency=t.currency,
            merchant=t.merchant,
            counterparty=t.counterparty,
            country=t.country,
            channel=t.channel,
            direction=t.direction,
            session=SimpleNamespace(),
        )
        for rule in rules:
            if rule.rule_id in ("HighValueTransaction", "SanctionsKeywordMatch", "HighRiskCountry"):
                rule_results.extend(rule.evaluate(stateless_ctx))
    else:
        with session_scope() as session:
            ctx.session = session
            for rule in rules:
                rule_results.extend(rule.evaluate(ctx))

    score, band = compute_transaction_risk(
        base_risk, rule_results, max_score=max_score, low_threshold=low_t, medium_threshold=med_t
    )
    return ScoreResponse(
        risk_score=round(score, 2),
        band=band,
        rule_hits=[
            RuleHit(
                rule_id=r.rule_id,
                severity=r.severity,
                reason=r.reason,
                evidence_fields=r.evidence_fields,
                score_delta=r.score_delta,
            )
            for r in rule_results
        ],
    )


@app.get("/alerts")
def list_alerts(
    limit: int = Query(50, ge=1, le=1000),
    cursor: str | None = Query(None, description="Opaque cursor for next page"),
    severity: str | None = Query(None),
    correlation_id: str | None = Query(None, description="Filter by run correlation_id"),
) -> dict[str, Any]:
    """Fetch alerts with cursor-based pagination and optional filters."""
    from sqlalchemy import select

    from aml_monitoring.pagination import paginate_query

    with session_scope() as session:
        stmt = select(Alert)
        if severity:
            stmt = stmt.where(Alert.severity == severity)
        if correlation_id is not None:
            stmt = stmt.where(Alert.correlation_id == correlation_id)
        items, next_cursor = paginate_query(
            stmt, session, id_column=Alert.id, cursor=cursor, limit=limit,
        )
        return {
            "items": [AlertResponse.model_validate(a) for a in items],
            "next_cursor": next_cursor,
        }


@app.patch("/alerts/{alert_id}", response_model=AlertResponse)
async def patch_alert(
    alert_id: int, request: Request, _actor: str = Depends(require_api_key_write)
) -> AlertResponse:
    """Update alert status and/or disposition. Audited with correlation_id and actor."""
    from sqlalchemy import select

    try:
        body = await request.json()
    except Exception as err:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from err
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    status = body.get("status")
    disposition = body.get("disposition")
    if status is not None and status not in ALERT_STATUS_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {sorted(ALERT_STATUS_VALUES)}",
        )
    if disposition is not None and disposition not in ALERT_DISPOSITION_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"disposition must be one of {sorted(ALERT_DISPOSITION_VALUES)} or omit",
        )
    if status is None and disposition is None:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one of status or disposition",
        )
    with session_scope() as session:
        alert = session.execute(select(Alert).where(Alert.id == alert_id)).scalar_one_or_none()
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")
        old_status = alert.status if alert.status else "open"
        old_disposition = alert.disposition
        if status is not None:
            alert.status = status
        if disposition is not None:
            alert.disposition = disposition
        alert.updated_at = datetime.now(UTC)
        row = session.execute(
            select(Transaction.config_hash).where(Transaction.id == alert.transaction_id)
        ).first()
        config_hash = row[0] if row else get_config_hash(get_config())
        session.add(
            AuditLog(
                correlation_id=get_correlation_id(),
                action="disposition_update",
                entity_type="alert",
                entity_id=str(alert_id),
                actor=_actor,
                details_json={
                    "old_status": old_status,
                    "new_status": alert.status,
                    "old_disposition": old_disposition,
                    "new_disposition": alert.disposition,
                    "config_hash": config_hash,
                },
            )
        )
        session.flush()
        session.refresh(alert)
        return AlertResponse.model_validate(alert)


@app.get("/transactions/{transaction_id}", response_model=TransactionResponse)
def get_transaction(transaction_id: int) -> TransactionResponse:
    """Get transaction by ID with alerts."""
    from sqlalchemy import select

    with session_scope() as session:
        txn = session.execute(
            select(Transaction).where(Transaction.id == transaction_id)
        ).scalar_one_or_none()
        if not txn:
            raise HTTPException(status_code=404, detail="Transaction not found")
        alerts = [AlertResponse.model_validate(a) for a in txn.alerts]
        return TransactionResponse(
            id=txn.id,
            account_id=txn.account_id,
            ts=txn.ts,
            amount=txn.amount,
            currency=txn.currency or "USD",
            risk_score=txn.risk_score,
            alerts=alerts,
        )
