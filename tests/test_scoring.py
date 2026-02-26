"""Unit tests for scoring."""

from aml_monitoring.schemas import RuleResult
from aml_monitoring.scoring import (
    compute_transaction_risk,
    normalize_score,
    score_band,
)


def test_normalize_score() -> None:
    assert normalize_score(50) == 50
    assert normalize_score(150, 100) == 100
    assert normalize_score(-10, 100) == 0


def test_score_band() -> None:
    assert score_band(20) == "low"
    assert score_band(50) == "medium"
    assert score_band(80) == "high"
    assert score_band(33, 33, 66) == "medium"
    assert score_band(32.9, 33, 66) == "low"


def test_compute_transaction_risk() -> None:
    base = 10.0
    no_hits: list[RuleResult] = []
    score, band = compute_transaction_risk(base, no_hits)
    assert score == 10.0
    assert band == "low"

    hits = [
        RuleResult(rule_id="R1", severity="high", reason="x", evidence_fields=None, score_delta=25),
    ]
    score, band = compute_transaction_risk(base, hits)
    assert score == 35.0
    assert band == "medium"

    hits2 = [
        RuleResult(rule_id="R1", severity="high", reason="x", evidence_fields=None, score_delta=60),
    ]
    score, band = compute_transaction_risk(base, hits2, max_score=100)
    assert score == 70.0
    assert band == "high"
