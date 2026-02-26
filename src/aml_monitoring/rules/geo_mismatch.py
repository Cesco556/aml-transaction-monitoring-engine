"""Geo mismatch: country changes unusually within window for same customer."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from aml_monitoring.models import Account, Transaction
from aml_monitoring.rules.base import BaseRule, RuleContext
from aml_monitoring.schemas import RuleResult


class GeoMismatchRule(BaseRule):
    rule_id = "GeoMismatch"

    def __init__(self, config: dict) -> None:
        self.window_minutes = int(config.get("window_minutes", 60))
        self.max_countries = int(config.get("max_countries_in_window", 2))

    def evaluate(self, ctx: RuleContext) -> list[RuleResult]:
        if not ctx.country:
            return []
        window_start = ctx.ts - timedelta(minutes=self.window_minutes)
        stmt = (
            select(Transaction.country)
            .join(Account, Account.id == Transaction.account_id)
            .where(Account.customer_id == ctx.customer_id)
            .where(Transaction.ts >= window_start)
            .where(Transaction.ts <= ctx.ts)
            .where(Transaction.country.isnot(None))
            .distinct()
        )
        rows = ctx.session.execute(stmt).fetchall()
        countries = {r[0] for r in rows if r[0]}
        if len(countries) > self.max_countries:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    severity="medium",
                    reason=f"Unusual country spread: {len(countries)} countries in {self.window_minutes} min",
                    evidence_fields={
                        "countries": list(countries),
                        "window_minutes": self.window_minutes,
                    },
                    score_delta=15.0,
                )
            ]
        return []
