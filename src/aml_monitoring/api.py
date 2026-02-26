"""FastAPI app: score single transaction, fetch alerts."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from aml_monitoring import ENGINE_VERSION, RULES_VERSION
from aml_monitoring.audit_context import get_correlation_id, set_audit_context
from aml_monitoring.auth import require_api_key_write
from aml_monitoring.cases_api import cases_router
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


app = FastAPI(title="AML Monitoring API", version="0.1.0", lifespan=lifespan)


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

app.include_router(cases_router)


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


@app.get("/alerts", response_model=list[AlertResponse])
def list_alerts(
    limit: int = Query(100, ge=1, le=1000),
    severity: str | None = Query(None),
    correlation_id: str | None = Query(None, description="Filter by run correlation_id"),
) -> list[AlertResponse]:
    """Fetch alerts with optional severity and correlation_id filter."""
    from sqlalchemy import select

    with session_scope() as session:
        stmt = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
        if severity:
            stmt = stmt.where(Alert.severity == severity)
        if correlation_id is not None:
            stmt = stmt.where(Alert.correlation_id == correlation_id)
        alerts = list(session.execute(stmt).scalars().all())
        return [AlertResponse.model_validate(a) for a in alerts]


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
