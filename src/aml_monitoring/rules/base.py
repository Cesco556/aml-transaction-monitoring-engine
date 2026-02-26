"""Base rule interface and context."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from aml_monitoring.schemas import RuleResult


def stable_rule_hash(rule_id: str, salt: str = "v1") -> str:
    """Stable hash for rule (rule_id + salt) for audit evidence."""
    return hashlib.sha256(f"{rule_id}:{salt}".encode()).hexdigest()[:16]


@dataclass
class RuleContext:
    """Context passed to rules: current transaction + session for DB lookups."""

    transaction_id: int
    account_id: int
    customer_id: int
    ts: Any  # datetime
    amount: float
    currency: str
    merchant: str | None
    counterparty: str | None
    country: str | None
    channel: str | None
    direction: str | None
    session: Any  # SQLAlchemy Session


class BaseRule(ABC):
    """Base class for detection rules."""

    rule_id: str = "base"
    RULE_HASH: str = ""  # Override in subclass for stable per-rule hash; else derived from rule_id.

    def get_rule_hash(self) -> str:
        """Stable hash for this rule (stored in alert evidence_fields)."""
        return self.RULE_HASH or stable_rule_hash(self.rule_id)

    def reset_run_state(self) -> None:  # noqa: B027
        """Called at start of each run_rules batch; override to clear per-run state."""
        pass

    @abstractmethod
    def evaluate(self, ctx: RuleContext) -> list[RuleResult]:
        """Evaluate rule; return list of RuleResult (empty if no hit)."""
        ...
