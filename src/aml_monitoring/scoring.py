"""Risk scoring v2: severity multipliers, temporal decay, customer risk profiles, composite scoring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from aml_monitoring.schemas import RuleResult


# ---------------------------------------------------------------------------
# Default scoring configuration
# ---------------------------------------------------------------------------

DEFAULT_SEVERITY_MULTIPLIERS: dict[str, float] = {
    "critical": 2.0,
    "high": 1.5,
    "medium": 1.0,
    "low": 0.5,
}

DEFAULT_DECAY_WINDOWS: list[dict[str, Any]] = [
    {"within_hours": 24, "factor": 1.0},
    {"within_hours": 168, "factor": 0.7},   # 7 days
    {"within_hours": 720, "factor": 0.4},   # 30 days
]
DEFAULT_DECAY_FLOOR: float = 0.2

DEFAULT_SCORING_PROFILES: dict[str, dict[str, Any]] = {
    "conservative": {
        "severity_multipliers": {"critical": 2.5, "high": 2.0, "medium": 1.5, "low": 1.0},
        "thresholds": {"low": 25, "medium": 50, "high": 100},
        "base_risk_per_customer": 15,
    },
    "balanced": {
        "severity_multipliers": {"critical": 2.0, "high": 1.5, "medium": 1.0, "low": 0.5},
        "thresholds": {"low": 33, "medium": 66, "high": 100},
        "base_risk_per_customer": 10,
    },
    "aggressive": {
        "severity_multipliers": {"critical": 1.5, "high": 1.0, "medium": 0.7, "low": 0.3},
        "thresholds": {"low": 45, "medium": 75, "high": 100},
        "base_risk_per_customer": 5,
    },
}


# ---------------------------------------------------------------------------
# Core scoring functions (backward-compatible)
# ---------------------------------------------------------------------------


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
    Backward-compatible: no severity multipliers or decay applied.
    """
    total = base_risk
    for r in rule_results:
        total += r.score_delta
    score = normalize_score(total, max_score)
    band = score_band(score, low_threshold, medium_threshold)
    return score, band


# ---------------------------------------------------------------------------
# Severity-weighted scoring
# ---------------------------------------------------------------------------


def get_severity_multiplier(
    severity: str,
    multipliers: dict[str, float] | None = None,
) -> float:
    """Return multiplier for a severity level."""
    m = multipliers or DEFAULT_SEVERITY_MULTIPLIERS
    return m.get(severity.lower(), 1.0)


def apply_severity_multiplier(
    score_delta: float,
    severity: str,
    multipliers: dict[str, float] | None = None,
) -> float:
    """Apply severity multiplier to a raw score_delta."""
    return score_delta * get_severity_multiplier(severity, multipliers)


# ---------------------------------------------------------------------------
# Temporal decay
# ---------------------------------------------------------------------------


def compute_decay_factor(
    hit_time: datetime,
    now: datetime | None = None,
    decay_windows: list[dict[str, Any]] | None = None,
    decay_floor: float | None = None,
) -> float:
    """
    Compute decay factor based on how old a rule hit is.

    decay_windows: list of {within_hours: int, factor: float} sorted by within_hours ascending.
    Hits older than all windows get decay_floor.
    """
    if now is None:
        now = datetime.now(UTC)
    windows = decay_windows or DEFAULT_DECAY_WINDOWS
    floor = decay_floor if decay_floor is not None else DEFAULT_DECAY_FLOOR

    age = now - hit_time
    age_hours = age.total_seconds() / 3600.0

    for w in sorted(windows, key=lambda x: x["within_hours"]):
        if age_hours <= w["within_hours"]:
            return float(w["factor"])
    return floor


def apply_temporal_decay(
    score_delta: float,
    hit_time: datetime,
    now: datetime | None = None,
    decay_windows: list[dict[str, Any]] | None = None,
    decay_floor: float | None = None,
) -> float:
    """Apply temporal decay to a score_delta based on hit age."""
    factor = compute_decay_factor(hit_time, now, decay_windows, decay_floor)
    return score_delta * factor


# ---------------------------------------------------------------------------
# Customer risk profile
# ---------------------------------------------------------------------------


def compute_customer_risk_profile(
    alert_history: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Compute cumulative customer risk profile from alert history.

    Each alert dict should have:
      - severity: str
      - created_at: datetime

    Returns dict with:
      - alert_count: int
      - severity_distribution: {severity: count}
      - days_since_last_alert: float | None
      - risk_adjustment: float (additive adjustment to base_risk)
    """
    if now is None:
        now = datetime.now(UTC)

    if not alert_history:
        return {
            "alert_count": 0,
            "severity_distribution": {},
            "days_since_last_alert": None,
            "risk_adjustment": 0.0,
        }

    severity_dist: dict[str, int] = {}
    latest_alert_time: datetime | None = None

    for alert in alert_history:
        sev = alert.get("severity", "medium").lower()
        severity_dist[sev] = severity_dist.get(sev, 0) + 1
        created = alert.get("created_at")
        if created and (latest_alert_time is None or created > latest_alert_time):
            latest_alert_time = created

    days_since_last = None
    recency_factor = 1.0
    if latest_alert_time:
        delta = now - latest_alert_time
        days_since_last = delta.total_seconds() / 86400.0
        # More recent alerts = higher risk adjustment
        if days_since_last <= 1:
            recency_factor = 2.0
        elif days_since_last <= 7:
            recency_factor = 1.5
        elif days_since_last <= 30:
            recency_factor = 1.0
        else:
            recency_factor = 0.5

    # Weighted severity score
    severity_weights = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}
    weighted_severity = sum(
        severity_weights.get(sev, 1.0) * count
        for sev, count in severity_dist.items()
    )

    # Risk adjustment: combination of alert volume, severity weight, and recency
    alert_count = len(alert_history)
    volume_factor = min(alert_count / 5.0, 3.0)  # caps at 3x for 15+ alerts
    risk_adjustment = weighted_severity * volume_factor * recency_factor

    return {
        "alert_count": alert_count,
        "severity_distribution": severity_dist,
        "days_since_last_alert": round(days_since_last, 2) if days_since_last is not None else None,
        "risk_adjustment": round(risk_adjustment, 2),
    }


# ---------------------------------------------------------------------------
# Composite scoring (v2)
# ---------------------------------------------------------------------------


def get_scoring_profile(
    profile_name: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Load a scoring profile by name from config or defaults.

    Config should have scoring.profiles dict keyed by profile name.
    """
    profiles = DEFAULT_SCORING_PROFILES.copy()
    if config:
        scoring_cfg = config.get("scoring", {})
        custom_profiles = scoring_cfg.get("profiles", {})
        profiles.update(custom_profiles)
    if profile_name not in profiles:
        raise ValueError(
            f"Unknown scoring profile {profile_name!r}. "
            f"Available: {sorted(profiles.keys())}"
        )
    return profiles[profile_name]


def compute_transaction_risk_v2(
    base_risk: float,
    rule_results: list[RuleResult],
    hit_time: datetime | None = None,
    now: datetime | None = None,
    scoring_config: dict[str, Any] | None = None,
    profile_name: str | None = None,
) -> tuple[float, str, dict[str, Any]]:
    """
    Enhanced risk scoring with severity multipliers, temporal decay, and profiles.

    Returns (risk_score, band, details_dict).
    """
    cfg = scoring_config or {}

    # Load profile if specified
    if profile_name:
        profile = get_scoring_profile(profile_name, {"scoring": cfg})
        severity_multipliers = profile.get("severity_multipliers", DEFAULT_SEVERITY_MULTIPLIERS)
        thresholds = profile.get("thresholds", {"low": 33, "medium": 66})
        max_score = float(thresholds.get("high", 100))
    else:
        severity_multipliers = cfg.get("severity_multipliers", DEFAULT_SEVERITY_MULTIPLIERS)
        thresholds = cfg.get("thresholds", {"low": 33, "medium": 66})
        max_score = float(cfg.get("max_score", 100))

    low_threshold = float(thresholds.get("low", 33))
    medium_threshold = float(thresholds.get("medium", 66))

    # Decay config
    decay_windows = cfg.get("temporal_decay", {}).get("windows", DEFAULT_DECAY_WINDOWS)
    decay_floor = cfg.get("temporal_decay", {}).get("floor", DEFAULT_DECAY_FLOOR)
    decay_enabled = cfg.get("temporal_decay", {}).get("enabled", False)

    total = base_risk
    breakdown: list[dict[str, Any]] = []

    for r in rule_results:
        raw_delta = r.score_delta
        # Apply severity multiplier
        weighted_delta = apply_severity_multiplier(raw_delta, r.severity, severity_multipliers)
        # Apply temporal decay if enabled and hit_time provided
        if decay_enabled and hit_time is not None:
            weighted_delta = apply_temporal_decay(
                weighted_delta, hit_time, now, decay_windows, decay_floor
            )
        total += weighted_delta
        breakdown.append({
            "rule_id": r.rule_id,
            "raw_delta": raw_delta,
            "weighted_delta": round(weighted_delta, 2),
            "severity": r.severity,
        })

    score = normalize_score(total, max_score)
    band = score_band(score, low_threshold, medium_threshold)

    details = {
        "base_risk": base_risk,
        "breakdown": breakdown,
        "raw_total": round(total, 2),
        "final_score": score,
        "band": band,
        "profile": profile_name,
    }

    return score, band, details
