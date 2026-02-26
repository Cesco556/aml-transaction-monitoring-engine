"""Structuring/smurfing: many transactions just below threshold in window."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from aml_monitoring.models import Transaction
from aml_monitoring.rules.base import BaseRule, RuleContext
from aml_monitoring.schemas import RuleResult


class StructuringSmurfingRule(BaseRule):
    rule_id = "StructuringSmurfing"

    def __init__(self, config: dict) -> None:
        self.threshold = float(config.get("threshold_amount", 9500))
        self.min_transactions = int(config.get("min_transactions", 3))
        self.window_minutes = int(config.get("window_minutes", 60))

    def evaluate(self, ctx: RuleContext) -> list[RuleResult]:
        window_start = ctx.ts - timedelta(minutes=self.window_minutes)
        # Count transactions in window that are just below threshold (e.g. >= threshold * 0.9)
        floor = self.threshold * 0.8
        stmt = (
            select(func.count(Transaction.id))
            .where(Transaction.account_id == ctx.account_id)
            .where(Transaction.ts >= window_start)
            .where(Transaction.ts <= ctx.ts)
            .where(Transaction.amount >= floor)
            .where(Transaction.amount < self.threshold)
        )
        count = ctx.session.execute(stmt).scalar() or 0
        if count >= self.min_transactions:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    severity="high",
                    reason=f"{count} transactions just below threshold {self.threshold} in {self.window_minutes} min",
                    evidence_fields={
                        "count": count,
                        "threshold": self.threshold,
                        "window_minutes": self.window_minutes,
                    },
                    score_delta=30.0,
                )
            ]
        return []
