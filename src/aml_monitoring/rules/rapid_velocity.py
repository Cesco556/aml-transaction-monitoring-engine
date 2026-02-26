"""Rapid velocity: N+ transactions from same account within T minutes."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from aml_monitoring.models import Transaction
from aml_monitoring.rules.base import BaseRule, RuleContext
from aml_monitoring.schemas import RuleResult


class RapidVelocityRule(BaseRule):
    rule_id = "RapidVelocity"

    def __init__(self, config: dict) -> None:
        self.min_transactions = int(config.get("min_transactions", 5))
        self.window_minutes = int(config.get("window_minutes", 15))

    def evaluate(self, ctx: RuleContext) -> list[RuleResult]:
        window_start = ctx.ts - timedelta(minutes=self.window_minutes)
        stmt = (
            select(func.count(Transaction.id))
            .where(Transaction.account_id == ctx.account_id)
            .where(Transaction.ts >= window_start)
            .where(Transaction.ts <= ctx.ts)
        )
        count = ctx.session.execute(stmt).scalar() or 0
        if count >= self.min_transactions:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    severity="medium",
                    reason=f"{count} transactions from same account within {self.window_minutes} minutes",
                    evidence_fields={
                        "count": count,
                        "window_minutes": self.window_minutes,
                        "account_id": ctx.account_id,
                    },
                    score_delta=20.0,
                )
            ]
        return []
