"""Run all detection rules on transactions and persist alerts + risk scores."""

from __future__ import annotations

import logging
import time

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from aml_monitoring import ENGINE_VERSION, RULES_VERSION
from aml_monitoring.audit_context import get_actor, get_correlation_id
from aml_monitoring.config import get_config, get_config_hash
from aml_monitoring.db import session_scope
from aml_monitoring.models import Account, Alert, AuditLog, Transaction
from aml_monitoring.rules import get_all_rules
from aml_monitoring.rules.base import RuleContext
from aml_monitoring.schemas import RuleResult
from aml_monitoring.scoring import compute_transaction_risk

log = logging.getLogger(__name__)
PROGRESS_INTERVAL = 5000  # log progress every N transactions


def _get_last_processed_id(session, correlation_id: str) -> int | None:
    """Return last_processed_id from most recent run_rules audit for this correlation_id."""
    row = session.execute(
        select(AuditLog.details_json)
        .where(AuditLog.action == "run_rules")
        .where(AuditLog.correlation_id == correlation_id)
        .order_by(AuditLog.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not row or not isinstance(row, dict):
        return None
    val = row.get("last_processed_id")
    return int(val) if val is not None else None


def run_rules(
    config_path: str | None = None,
    resume_from_correlation_id: str | None = None,
) -> tuple[int, int]:
    """
    Run all enabled rules on every transaction (optionally in chunks); persist alerts and risk_score.
    Sets config_hash, rules_version, engine_version on Alert and Transaction.
    When resume_from_correlation_id is set, continues from last_processed_id of that run.
    Returns (transactions_processed, alerts_created). Writes audit log(s) with duration and checkpoint.
    """
    config = get_config(config_path)
    config_hash = get_config_hash(config)
    rules = get_all_rules(config)
    for rule in rules:
        rule.reset_run_state()
    scoring_cfg = config.get("scoring", {})
    base_risk = float(scoring_cfg.get("base_risk_per_customer", 10))
    max_score = float(scoring_cfg.get("max_score", 100))
    thresholds = scoring_cfg.get("thresholds", {})
    low_t = float(thresholds.get("low", 33))
    med_t = float(thresholds.get("medium", 66))
    run_rules_cfg = config.get("run_rules") or {}
    chunk_size = int(run_rules_cfg.get("chunk_size", 0))

    run_correlation_id = resume_from_correlation_id or get_correlation_id()
    start = time.perf_counter()
    processed_total = 0
    alerts_total = 0
    chunk_index = 0
    last_processed_id: int | None = None
    total_transactions: int | None = None
    if chunk_size > 0:
        with session_scope() as session:
            total_transactions = session.execute(select(func.count(Transaction.id))).scalar() or 0

    if resume_from_correlation_id:
        with session_scope() as session:
            last_processed_id = _get_last_processed_id(session, resume_from_correlation_id)

    while True:
        with session_scope() as session:
            load_opts = joinedload(Transaction.account).joinedload(Account.customer)
            if chunk_size > 0:
                stmt = (
                    select(Transaction)
                    .options(load_opts)
                    .where(Transaction.id > (last_processed_id or 0))
                    .order_by(Transaction.id)
                    .limit(chunk_size)
                )
                txns = list(session.execute(stmt).unique().scalars().all())
            else:
                stmt = select(Transaction).options(load_opts).order_by(Transaction.id)
                txns = list(session.execute(stmt).unique().scalars().all())

            if not txns:
                break

            if total_transactions is None:
                total_transactions = len(txns)
            total_in_run = len(txns) if chunk_size <= 0 else (total_transactions or len(txns))

            processed_chunk = 0
            alerts_chunk = 0
            for txn in txns:
                acct = txn.account
                cust = acct.customer
                ctx = RuleContext(
                    transaction_id=txn.id,
                    account_id=txn.account_id,
                    customer_id=cust.id,
                    ts=txn.ts,
                    amount=txn.amount,
                    currency=txn.currency or "USD",
                    merchant=txn.merchant,
                    counterparty=txn.counterparty,
                    country=txn.country,
                    channel=txn.channel,
                    direction=txn.direction,
                    session=session,
                )
                all_hits: list[RuleResult] = []
                for rule in rules:
                    hits = rule.evaluate(ctx)
                    for hit in hits:
                        ev = dict(hit.evidence_fields or {})
                        ev["rule_hash"] = rule.get_rule_hash()
                        alert = Alert(
                            transaction_id=txn.id,
                            rule_id=hit.rule_id,
                            severity=hit.severity,
                            score=hit.score_delta,
                            reason=hit.reason,
                            evidence_fields=ev,
                            config_hash=config_hash,
                            rules_version=RULES_VERSION,
                            engine_version=ENGINE_VERSION,
                            correlation_id=run_correlation_id,
                        )
                        session.add(alert)
                        alerts_chunk += 1
                        all_hits.append(hit)
                base = float(cust.base_risk) if cust else base_risk
                score, _ = compute_transaction_risk(
                    base, all_hits, max_score=max_score, low_threshold=low_t, medium_threshold=med_t
                )
                txn.risk_score = score
                txn.config_hash = config_hash
                txn.rules_version = RULES_VERSION
                txn.engine_version = ENGINE_VERSION
                processed_chunk += 1
                last_processed_id = txn.id
                so_far = processed_total + processed_chunk
                if so_far % PROGRESS_INTERVAL == 0 or so_far == total_in_run:
                    log.info(
                        "run-rules progress: %s / %s transactions, %s alerts",
                        so_far,
                        total_in_run,
                        alerts_total + alerts_chunk,
                    )

            processed_total += processed_chunk
            alerts_total += alerts_chunk
            duration_chunk = time.perf_counter() - start
            details = {
                "processed": processed_total,
                "alerts_created": alerts_total,
                "duration_seconds": round(duration_chunk, 3),
                "config_hash": config_hash,
                "rules_version": RULES_VERSION,
                "engine_version": ENGINE_VERSION,
                "chunk_index": chunk_index,
                "last_processed_id": last_processed_id,
            }
            session.add(
                AuditLog(
                    correlation_id=run_correlation_id,
                    action="run_rules",
                    entity_type="batch",
                    entity_id="all",
                    actor=get_actor(),
                    details_json=details,
                )
            )
            chunk_index += 1
            if chunk_size <= 0 or len(txns) < chunk_size:
                break

    return processed_total, alerts_total
