"""Tests for Pydantic schemas."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from aml_monitoring.schemas import RuleHit, ScoreRequest, TransactionCreate


def test_transaction_create_valid() -> None:
    t = TransactionCreate(
        account_id=1,
        ts=datetime.now(UTC),
        amount=100.0,
        currency="USD",
    )
    assert t.currency == "USD"
    assert t.amount == 100.0


def test_transaction_create_invalid_amount() -> None:
    with pytest.raises(ValidationError):
        TransactionCreate(
            account_id=1,
            ts=datetime.now(UTC),
            amount=1e15,  # too large
            currency="USD",
        )


def test_score_request() -> None:
    t = TransactionCreate(account_id=1, ts=datetime.now(UTC), amount=100, currency="USD")
    req = ScoreRequest(transaction=t)
    assert req.transaction.amount == 100


def test_rule_hit() -> None:
    h = RuleHit(rule_id="R1", severity="high", reason="test", score_delta=10.0)
    assert h.rule_id == "R1"
    assert h.evidence_fields is None
