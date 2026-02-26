"""Risk scoring: base + deltas, normalized 0-100 with bands."""

from __future__ import annotations

from aml_monitoring.schemas import RuleResult


def normalize_score(raw: float, max_score: float = 100) -> float:
    """Clamp to [0, max_score]."""
    return max(0.0, min(float(raw), max_score))


def score_band(score: float, low: float = 33, medium: float = 66) -> str:
    """Return low / medium / high band."""
    if score < low:
        return "low"
    if score < medium:
        return "medium"
    return "high"


def compute_transaction_risk(
    base_risk: float,
    rule_results: list[RuleResult],
    max_score: float = 100,
    low_threshold: float = 33,
    medium_threshold: float = 66,
) -> tuple[float, str]:
    """
    Compute final risk score and band from base + rule deltas.
    Returns (risk_score, band).
    """
    total = base_risk
    for r in rule_results:
        total += r.score_delta
    score = normalize_score(total, max_score)
    band = score_band(score, low_threshold, medium_threshold)
    return score, band
