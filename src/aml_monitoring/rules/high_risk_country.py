"""High-risk country: transaction involving country from config list."""

from __future__ import annotations

from aml_monitoring.rules.base import BaseRule, RuleContext
from aml_monitoring.schemas import RuleResult


class HighRiskCountryRule(BaseRule):
    rule_id = "HighRiskCountry"

    def __init__(self, config: dict) -> None:
        self.countries = {c.strip().upper() for c in config.get("countries", []) if c}
        self.list_version = str(config.get("list_version", "unknown"))
        self.effective_date = str(config.get("effective_date", ""))
        self.severity = str(config.get("severity", "high"))
        self.score_delta = float(config.get("score_delta", 25.0))

    def evaluate(self, ctx: RuleContext) -> list[RuleResult]:
        if not ctx.country:
            return []
        country_upper = ctx.country.strip().upper()[:3]
        if country_upper in self.countries:
            evidence = {
                "country": ctx.country,
                "list_version": self.list_version,
                "effective_date": self.effective_date,
            }
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    severity=self.severity,
                    reason=f"Transaction involves high-risk country: {ctx.country}",
                    evidence_fields=evidence,
                    score_delta=self.score_delta,
                )
            ]
        return []
