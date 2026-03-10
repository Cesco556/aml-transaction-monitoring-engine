"""High-value transaction rule."""

from __future__ import annotations

from aml_monitoring.rules.base import BaseRule, RuleContext
from aml_monitoring.schemas import RuleResult


class HighValueTransactionRule(BaseRule):
    rule_id = "HighValueTransaction"

    def __init__(self, config: dict) -> None:
        self.threshold = float(config.get("threshold_amount", 10_000))
        self.currency_default = config.get("currency_default", "USD")
        self.severity = str(config.get("severity", "high"))
        self.score_delta = float(config.get("score_delta", 25.0))

    def evaluate(self, ctx: RuleContext) -> list[RuleResult]:
        if ctx.amount >= self.threshold:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    severity=self.severity,
                    reason=f"Transaction amount {ctx.amount} >= threshold {self.threshold}",
                    evidence_fields={"amount": ctx.amount, "threshold": self.threshold},
                    score_delta=self.score_delta,
                )
            ]
        return []
