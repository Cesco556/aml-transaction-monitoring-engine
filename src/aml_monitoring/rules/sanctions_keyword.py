"""Sanctions keyword match (toy): counterparty name contains keyword from config."""

from __future__ import annotations

from aml_monitoring.rules.base import BaseRule, RuleContext
from aml_monitoring.schemas import RuleResult


class SanctionsKeywordRule(BaseRule):
    rule_id = "SanctionsKeywordMatch"

    def __init__(self, config: dict) -> None:
        self.keywords = [k.lower() for k in config.get("keywords", [])]
        self.list_version = str(config.get("list_version", "unknown"))
        self.effective_date = str(config.get("effective_date", ""))

    def evaluate(self, ctx: RuleContext) -> list[RuleResult]:
        if not ctx.counterparty:
            return []
        cp_lower = ctx.counterparty.lower()
        for kw in self.keywords:
            if kw in cp_lower:
                evidence = {
                    "counterparty": ctx.counterparty,
                    "keyword": kw,
                    "list_version": self.list_version,
                    "effective_date": self.effective_date,
                }
                return [
                    RuleResult(
                        rule_id=self.rule_id,
                        severity="high",
                        reason=f"Counterparty name matches sanctions keyword: {kw!r}",
                        evidence_fields=evidence,
                        score_delta=40.0,
                    )
                ]
        return []
