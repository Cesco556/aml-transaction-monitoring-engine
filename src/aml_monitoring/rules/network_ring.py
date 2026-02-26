"""Network ring indicator: accounts sharing counterparties (ring structure)."""

from __future__ import annotations

from aml_monitoring.network.metrics import ring_signal
from aml_monitoring.rules.base import BaseRule, RuleContext
from aml_monitoring.schemas import RuleResult


class NetworkRingIndicatorRule(BaseRule):
    rule_id = "NetworkRingIndicator"

    def __init__(self, config: dict) -> None:
        self.min_shared_counterparties = int(config.get("min_shared_counterparties", 2))
        self.min_linked_accounts = int(config.get("min_linked_accounts", 2))
        self.lookback_days = int(config.get("lookback_days", 30))
        self.severity = str(config.get("severity", "high"))
        self.score_delta = float(config.get("score_delta", 40))
        self._seen_accounts: set[int] = set()

    def reset_run_state(self) -> None:
        self._seen_accounts.clear()

    def evaluate(self, ctx: RuleContext) -> list[RuleResult]:
        if ctx.account_id in self._seen_accounts:
            return []
        signal = ring_signal(ctx.account_id, ctx.session, self.lookback_days)
        if signal.overlap_count < self.min_shared_counterparties:
            return []
        if len(signal.linked_accounts) < self.min_linked_accounts:
            return []
        self._seen_accounts.add(ctx.account_id)
        return [
            RuleResult(
                rule_id=self.rule_id,
                severity=self.severity,
                reason=f"Account shares {signal.overlap_count} counterparties with {len(signal.linked_accounts)} other account(s) (ring pattern)",
                evidence_fields={
                    "linked_accounts": signal.linked_accounts,
                    "shared_counterparties": signal.shared_counterparties,
                    "overlap_count": signal.overlap_count,
                    "degree": signal.degree,
                    "lookback_days": self.lookback_days,
                },
                score_delta=self.score_delta,
            )
        ]
