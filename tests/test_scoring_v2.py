"""Tests for scoring engine v2: configurable score_delta, severity multipliers,
temporal decay, customer risk profiles, and composite scoring profiles."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from aml_monitoring.rules.base import RuleContext
from aml_monitoring.rules.geo_mismatch import GeoMismatchRule
from aml_monitoring.rules.high_risk_country import HighRiskCountryRule
from aml_monitoring.rules.high_value import HighValueTransactionRule
from aml_monitoring.rules.rapid_velocity import RapidVelocityRule
from aml_monitoring.rules.sanctions_keyword import SanctionsKeywordRule
from aml_monitoring.rules.structuring_smurfing import StructuringSmurfingRule
from aml_monitoring.schemas import RuleResult
from aml_monitoring.scoring import (
    DEFAULT_DECAY_FLOOR,
    DEFAULT_DECAY_WINDOWS,
    DEFAULT_SEVERITY_MULTIPLIERS,
    apply_severity_multiplier,
    apply_temporal_decay,
    compute_customer_risk_profile,
    compute_decay_factor,
    compute_transaction_risk,
    compute_transaction_risk_v2,
    get_scoring_profile,
    get_severity_multiplier,
    normalize_score,
    score_band,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(amount: float = 1000, counterparty: str | None = None, country: str | None = "USA") -> RuleContext:
    return RuleContext(
        transaction_id=1,
        account_id=1,
        customer_id=1,
        ts=datetime.now(UTC),
        amount=amount,
        currency="USD",
        merchant=None,
        counterparty=counterparty,
        country=country,
        channel=None,
        direction=None,
        session=SimpleNamespace(),
    )


# ===========================================================================
# 1. Configurable score_delta for each rule
# ===========================================================================


class TestConfigurableScoreDelta:
    """All rules should read score_delta from config with sensible defaults."""

    def test_high_value_default_score_delta(self) -> None:
        rule = HighValueTransactionRule({})
        assert rule.score_delta == 25.0
        results = rule.evaluate(_ctx(amount=50_000))
        assert results[0].score_delta == 25.0

    def test_high_value_custom_score_delta(self) -> None:
        rule = HighValueTransactionRule({"score_delta": 50.0, "threshold_amount": 1000})
        assert rule.score_delta == 50.0
        results = rule.evaluate(_ctx(amount=5000))
        assert results[0].score_delta == 50.0

    def test_high_value_custom_severity(self) -> None:
        rule = HighValueTransactionRule({"severity": "critical", "threshold_amount": 1000})
        results = rule.evaluate(_ctx(amount=5000))
        assert results[0].severity == "critical"

    def test_rapid_velocity_default_score_delta(self) -> None:
        rule = RapidVelocityRule({})
        assert rule.score_delta == 20.0

    def test_rapid_velocity_custom_score_delta(self) -> None:
        rule = RapidVelocityRule({"score_delta": 35.0})
        assert rule.score_delta == 35.0

    def test_sanctions_keyword_default_score_delta(self) -> None:
        rule = SanctionsKeywordRule({"keywords": ["test"]})
        assert rule.score_delta == 30.0
        results = rule.evaluate(_ctx(counterparty="test entity"))
        assert results[0].score_delta == 30.0

    def test_sanctions_keyword_custom_score_delta(self) -> None:
        rule = SanctionsKeywordRule({"keywords": ["test"], "score_delta": 45.0})
        results = rule.evaluate(_ctx(counterparty="test entity"))
        assert results[0].score_delta == 45.0

    def test_high_risk_country_default_score_delta(self) -> None:
        rule = HighRiskCountryRule({"countries": ["IR"]})
        assert rule.score_delta == 25.0
        results = rule.evaluate(_ctx(country="IR"))
        assert results[0].score_delta == 25.0

    def test_high_risk_country_custom_score_delta(self) -> None:
        rule = HighRiskCountryRule({"countries": ["IR"], "score_delta": 40.0})
        results = rule.evaluate(_ctx(country="IR"))
        assert results[0].score_delta == 40.0

    def test_geo_mismatch_default_score_delta(self) -> None:
        rule = GeoMismatchRule({})
        assert rule.score_delta == 15.0

    def test_geo_mismatch_custom_score_delta(self) -> None:
        rule = GeoMismatchRule({"score_delta": 22.0})
        assert rule.score_delta == 22.0

    def test_structuring_default_score_delta(self) -> None:
        rule = StructuringSmurfingRule({})
        assert rule.score_delta == 30.0

    def test_structuring_custom_score_delta(self) -> None:
        rule = StructuringSmurfingRule({"score_delta": 40.0})
        assert rule.score_delta == 40.0

    def test_structuring_custom_severity(self) -> None:
        rule = StructuringSmurfingRule({"severity": "critical"})
        assert rule.severity == "critical"


# ===========================================================================
# 2. Severity multipliers
# ===========================================================================


class TestSeverityMultipliers:
    def test_default_multipliers(self) -> None:
        assert get_severity_multiplier("critical") == 2.0
        assert get_severity_multiplier("high") == 1.5
        assert get_severity_multiplier("medium") == 1.0
        assert get_severity_multiplier("low") == 0.5

    def test_unknown_severity_defaults_to_1(self) -> None:
        assert get_severity_multiplier("unknown") == 1.0

    def test_apply_severity_multiplier(self) -> None:
        assert apply_severity_multiplier(10.0, "critical") == 20.0
        assert apply_severity_multiplier(10.0, "high") == 15.0
        assert apply_severity_multiplier(10.0, "medium") == 10.0
        assert apply_severity_multiplier(10.0, "low") == 5.0

    def test_custom_multipliers(self) -> None:
        custom = {"critical": 3.0, "high": 2.0, "medium": 1.0, "low": 0.25}
        assert apply_severity_multiplier(10.0, "critical", custom) == 30.0
        assert apply_severity_multiplier(10.0, "low", custom) == 2.5

    def test_case_insensitive(self) -> None:
        assert get_severity_multiplier("HIGH") == 1.5
        assert get_severity_multiplier("Critical") == 2.0


# ===========================================================================
# 3. Temporal decay
# ===========================================================================


class TestTemporalDecay:
    def test_within_24h(self) -> None:
        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        hit = now - timedelta(hours=12)
        assert compute_decay_factor(hit, now) == 1.0

    def test_within_7_days(self) -> None:
        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        hit = now - timedelta(days=3)
        assert compute_decay_factor(hit, now) == 0.7

    def test_within_30_days(self) -> None:
        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        hit = now - timedelta(days=15)
        assert compute_decay_factor(hit, now) == 0.4

    def test_older_than_30_days(self) -> None:
        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        hit = now - timedelta(days=60)
        assert compute_decay_factor(hit, now) == DEFAULT_DECAY_FLOOR

    def test_apply_temporal_decay(self) -> None:
        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        # Recent hit: full weight
        recent = now - timedelta(hours=6)
        assert apply_temporal_decay(20.0, recent, now) == 20.0
        # Week-old hit: 0.7x
        week_old = now - timedelta(days=5)
        assert apply_temporal_decay(20.0, week_old, now) == 14.0

    def test_custom_decay_windows(self) -> None:
        custom_windows = [
            {"within_hours": 12, "factor": 1.0},
            {"within_hours": 48, "factor": 0.5},
        ]
        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        hit_6h = now - timedelta(hours=6)
        hit_36h = now - timedelta(hours=36)
        hit_72h = now - timedelta(hours=72)
        assert compute_decay_factor(hit_6h, now, custom_windows) == 1.0
        assert compute_decay_factor(hit_36h, now, custom_windows) == 0.5
        assert compute_decay_factor(hit_72h, now, custom_windows) == DEFAULT_DECAY_FLOOR

    def test_custom_decay_floor(self) -> None:
        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        hit = now - timedelta(days=60)
        assert compute_decay_factor(hit, now, decay_floor=0.1) == 0.1

    def test_boundary_exactly_24h(self) -> None:
        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        hit = now - timedelta(hours=24)
        assert compute_decay_factor(hit, now) == 1.0


# ===========================================================================
# 4. Customer risk profile
# ===========================================================================


class TestCustomerRiskProfile:
    def test_empty_history(self) -> None:
        result = compute_customer_risk_profile([])
        assert result["alert_count"] == 0
        assert result["severity_distribution"] == {}
        assert result["days_since_last_alert"] is None
        assert result["risk_adjustment"] == 0.0

    def test_single_recent_alert(self) -> None:
        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        alerts = [{"severity": "high", "created_at": now - timedelta(hours=6)}]
        result = compute_customer_risk_profile(alerts, now)
        assert result["alert_count"] == 1
        assert result["severity_distribution"] == {"high": 1}
        assert result["days_since_last_alert"] is not None
        assert result["days_since_last_alert"] < 1.0
        assert result["risk_adjustment"] > 0

    def test_multiple_alerts_severity_distribution(self) -> None:
        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        alerts = [
            {"severity": "high", "created_at": now - timedelta(hours=2)},
            {"severity": "high", "created_at": now - timedelta(hours=5)},
            {"severity": "medium", "created_at": now - timedelta(days=3)},
            {"severity": "low", "created_at": now - timedelta(days=10)},
        ]
        result = compute_customer_risk_profile(alerts, now)
        assert result["alert_count"] == 4
        assert result["severity_distribution"]["high"] == 2
        assert result["severity_distribution"]["medium"] == 1
        assert result["severity_distribution"]["low"] == 1

    def test_old_alerts_lower_recency(self) -> None:
        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        recent_alerts = [{"severity": "high", "created_at": now - timedelta(hours=6)}]
        old_alerts = [{"severity": "high", "created_at": now - timedelta(days=60)}]
        recent_result = compute_customer_risk_profile(recent_alerts, now)
        old_result = compute_customer_risk_profile(old_alerts, now)
        # Recent alerts should produce higher risk adjustment
        assert recent_result["risk_adjustment"] > old_result["risk_adjustment"]

    def test_volume_increases_risk(self) -> None:
        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        few_alerts = [
            {"severity": "medium", "created_at": now - timedelta(days=2)}
        ]
        many_alerts = [
            {"severity": "medium", "created_at": now - timedelta(days=i)}
            for i in range(1, 11)
        ]
        few_result = compute_customer_risk_profile(few_alerts, now)
        many_result = compute_customer_risk_profile(many_alerts, now)
        assert many_result["risk_adjustment"] > few_result["risk_adjustment"]


# ===========================================================================
# 5. Composite scoring profiles
# ===========================================================================


class TestScoringProfiles:
    def test_get_default_profiles(self) -> None:
        balanced = get_scoring_profile("balanced")
        assert balanced["thresholds"]["low"] == 33
        conservative = get_scoring_profile("conservative")
        assert conservative["thresholds"]["low"] == 25
        aggressive = get_scoring_profile("aggressive")
        assert aggressive["thresholds"]["low"] == 45

    def test_unknown_profile_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown scoring profile"):
            get_scoring_profile("nonexistent")

    def test_custom_profile_from_config(self) -> None:
        config = {
            "scoring": {
                "profiles": {
                    "ultra_conservative": {
                        "severity_multipliers": {"critical": 3.0, "high": 2.5, "medium": 2.0, "low": 1.5},
                        "thresholds": {"low": 15, "medium": 40, "high": 100},
                        "base_risk_per_customer": 20,
                    }
                }
            }
        }
        profile = get_scoring_profile("ultra_conservative", config)
        assert profile["thresholds"]["low"] == 15

    def test_compute_v2_with_profile(self) -> None:
        hits = [
            RuleResult(rule_id="R1", severity="high", reason="x", evidence_fields=None, score_delta=20),
        ]
        # Balanced: high = 1.5x, so 20 * 1.5 = 30, + base 10 = 40
        score, band, details = compute_transaction_risk_v2(
            base_risk=10.0,
            rule_results=hits,
            profile_name="balanced",
        )
        assert score == 40.0
        assert band == "medium"  # 33 <= 40 < 66

    def test_conservative_vs_aggressive(self) -> None:
        hits = [
            RuleResult(rule_id="R1", severity="high", reason="x", evidence_fields=None, score_delta=20),
        ]
        _, band_cons, _ = compute_transaction_risk_v2(
            base_risk=15.0, rule_results=hits, profile_name="conservative"
        )
        _, band_aggr, _ = compute_transaction_risk_v2(
            base_risk=5.0, rule_results=hits, profile_name="aggressive"
        )
        # Conservative: high=2.0x => 20*2.0=40 + 15 = 55, thresholds 25/50 => high
        assert band_cons == "high"
        # Aggressive: high=1.0x => 20*1.0=20 + 5 = 25, thresholds 45/75 => low
        assert band_aggr == "low"


# ===========================================================================
# 6. V2 scoring integration
# ===========================================================================


class TestComputeTransactionRiskV2:
    def test_basic_v2_no_profile(self) -> None:
        hits = [
            RuleResult(rule_id="R1", severity="medium", reason="x", evidence_fields=None, score_delta=10),
        ]
        score, band, details = compute_transaction_risk_v2(
            base_risk=5.0, rule_results=hits
        )
        # medium = 1.0x, so 10 * 1.0 = 10, + 5 = 15
        assert score == 15.0
        assert details["breakdown"][0]["weighted_delta"] == 10.0

    def test_v2_with_decay_enabled(self) -> None:
        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        hit_time = now - timedelta(days=5)  # 0.7x decay
        hits = [
            RuleResult(rule_id="R1", severity="medium", reason="x", evidence_fields=None, score_delta=10),
        ]
        cfg = {"temporal_decay": {"enabled": True, "windows": DEFAULT_DECAY_WINDOWS, "floor": 0.2}}
        score, band, details = compute_transaction_risk_v2(
            base_risk=5.0,
            rule_results=hits,
            hit_time=hit_time,
            now=now,
            scoring_config=cfg,
        )
        # medium=1.0x, decay=0.7x => 10 * 1.0 * 0.7 = 7.0, + 5 = 12
        assert score == 12.0
        assert details["breakdown"][0]["weighted_delta"] == 7.0

    def test_v2_decay_disabled_by_default(self) -> None:
        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        hit_time = now - timedelta(days=60)
        hits = [
            RuleResult(rule_id="R1", severity="medium", reason="x", evidence_fields=None, score_delta=10),
        ]
        score, _, _ = compute_transaction_risk_v2(
            base_risk=5.0, rule_results=hits, hit_time=hit_time, now=now
        )
        # Decay not enabled, so full weight: 10 * 1.0 = 10 + 5 = 15
        assert score == 15.0

    def test_v2_details_structure(self) -> None:
        hits = [
            RuleResult(rule_id="R1", severity="high", reason="x", evidence_fields=None, score_delta=20),
            RuleResult(rule_id="R2", severity="low", reason="y", evidence_fields=None, score_delta=10),
        ]
        _, _, details = compute_transaction_risk_v2(
            base_risk=10.0, rule_results=hits
        )
        assert details["base_risk"] == 10.0
        assert len(details["breakdown"]) == 2
        assert details["breakdown"][0]["rule_id"] == "R1"
        assert details["breakdown"][0]["raw_delta"] == 20
        assert details["breakdown"][1]["rule_id"] == "R2"
        assert "final_score" in details
        assert "band" in details

    def test_v2_clamping(self) -> None:
        hits = [
            RuleResult(rule_id="R1", severity="critical", reason="x", evidence_fields=None, score_delta=80),
        ]
        score, band, _ = compute_transaction_risk_v2(
            base_risk=50.0, rule_results=hits
        )
        # critical=2.0x => 80*2.0=160 + 50 = 210, clamped to 100
        assert score == 100.0
        assert band == "high"


# ===========================================================================
# 7. Backward compatibility
# ===========================================================================


class TestBackwardCompatibility:
    """Original compute_transaction_risk must still work unchanged."""

    def test_original_scoring_unchanged(self) -> None:
        base = 10.0
        no_hits: list[RuleResult] = []
        score, band = compute_transaction_risk(base, no_hits)
        assert score == 10.0
        assert band == "low"

    def test_original_with_hits(self) -> None:
        hits = [
            RuleResult(rule_id="R1", severity="high", reason="x", evidence_fields=None, score_delta=25),
        ]
        score, band = compute_transaction_risk(10.0, hits)
        assert score == 35.0
        assert band == "medium"

    def test_normalize_and_band_unchanged(self) -> None:
        assert normalize_score(50) == 50
        assert normalize_score(150, 100) == 100
        assert normalize_score(-10) == 0
        assert score_band(20) == "low"
        assert score_band(50) == "medium"
        assert score_band(80) == "high"
