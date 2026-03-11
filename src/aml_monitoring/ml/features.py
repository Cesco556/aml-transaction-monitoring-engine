"""Feature engineering pipeline for ML anomaly detection."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from logging import getLogger

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aml_monitoring.models import Transaction
from aml_monitoring.rules.base import RuleContext

logger = getLogger(__name__)


def build_feature_matrix(session: Session) -> pd.DataFrame:
    """Query all transactions and build a feature matrix (one row per transaction).

    Returns a DataFrame indexed by transaction_id with numeric feature columns.
    """
    stmt = select(Transaction).order_by(Transaction.ts)
    txns = session.execute(stmt).scalars().all()

    if not txns:
        logger.warning("No transactions found — returning empty feature matrix.")
        return pd.DataFrame()

    # Pre-compute per-account statistics
    account_stats: dict[int, dict] = {}
    account_txns: dict[int, list[Transaction]] = {}
    for t in txns:
        account_txns.setdefault(t.account_id, []).append(t)

    for acct_id, acct_list in account_txns.items():
        amounts = [t.amount for t in acct_list]
        mean_amt = sum(amounts) / len(amounts)
        std_amt = (sum((a - mean_amt) ** 2 for a in amounts) / max(len(amounts) - 1, 1)) ** 0.5
        account_stats[acct_id] = {
            "mean": mean_amt,
            "std": max(std_amt, 1e-9),  # avoid division by zero
            "max": max(amounts),
            "count": len(amounts),
        }

    rows = []
    for t in txns:
        features = _extract_features_from_txn(t, account_stats, account_txns)
        features["transaction_id"] = t.id
        rows.append(features)

    df = pd.DataFrame(rows).set_index("transaction_id")
    logger.info("Built feature matrix: %d rows, %d features", len(df), len(df.columns))
    return df


def extract_single_features(ctx: RuleContext, session: Session) -> dict[str, float]:
    """Extract features for a single transaction (real-time scoring).

    Uses DB lookups to compute account-level stats up to the current transaction.
    """
    # Gather account history up to and including this transaction's timestamp
    stmt = (
        select(Transaction)
        .where(Transaction.account_id == ctx.account_id)
        .where(Transaction.ts <= ctx.ts)
        .order_by(Transaction.ts)
    )
    history = session.execute(stmt).scalars().all()

    amounts = [t.amount for t in history]
    mean_amt = sum(amounts) / max(len(amounts), 1)
    std_amt = (sum((a - mean_amt) ** 2 for a in amounts) / max(len(amounts) - 1, 1)) ** 0.5
    std_amt = max(std_amt, 1e-9)

    account_stats = {
        ctx.account_id: {
            "mean": mean_amt,
            "std": std_amt,
            "max": max(amounts) if amounts else 0,
            "count": len(amounts),
        }
    }
    account_txns = {ctx.account_id: history}

    # Build a lightweight Transaction-like object from context
    class _TxnProxy:
        pass

    proxy = _TxnProxy()
    proxy.id = ctx.transaction_id  # type: ignore[attr-defined]
    proxy.account_id = ctx.account_id  # type: ignore[attr-defined]
    proxy.amount = ctx.amount  # type: ignore[attr-defined]
    proxy.ts = ctx.ts  # type: ignore[attr-defined]
    proxy.counterparty = ctx.counterparty  # type: ignore[attr-defined]
    proxy.country = ctx.country  # type: ignore[attr-defined]

    return _extract_features_from_txn(proxy, account_stats, account_txns)  # type: ignore[arg-type]


def _extract_features_from_txn(
    txn,
    account_stats: dict[int, dict],
    account_txns: dict[int, list],
) -> dict[str, float]:
    """Compute feature dict for a single transaction."""
    stats = account_stats.get(txn.account_id, {"mean": 0, "std": 1, "max": 0, "count": 0})

    # Amount z-score
    amount_zscore = (txn.amount - stats["mean"]) / stats["std"]

    # Velocity: count of transactions in 1h and 24h windows before this txn
    acct_history = account_txns.get(txn.account_id, [])
    ts = txn.ts if isinstance(txn.ts, datetime) else txn.ts
    velocity_1h = sum(
        1
        for t in acct_history
        if t.id != getattr(txn, "id", None)
        and ts - timedelta(hours=1) <= t.ts <= ts
    )
    velocity_24h = sum(
        1
        for t in acct_history
        if t.id != getattr(txn, "id", None)
        and ts - timedelta(hours=24) <= t.ts <= ts
    )

    # Time-of-day encoding (cyclical)
    hour = ts.hour + ts.minute / 60.0
    time_of_day_sin = math.sin(2 * math.pi * hour / 24.0)
    time_of_day_cos = math.cos(2 * math.pi * hour / 24.0)

    # Counterparty diversity: unique counterparties in account history
    counterparties = {t.counterparty for t in acct_history if t.counterparty}
    counterparty_diversity = float(len(counterparties))

    # Country diversity: unique countries in account history
    countries = {t.country for t in acct_history if t.country}
    country_diversity = float(len(countries))

    return {
        "amount_zscore": amount_zscore,
        "velocity_1h": float(velocity_1h),
        "velocity_24h": float(velocity_24h),
        "counterparty_diversity": counterparty_diversity,
        "country_diversity": country_diversity,
        "time_of_day_sin": time_of_day_sin,
        "time_of_day_cos": time_of_day_cos,
    }
