"""Rule-based detection modules."""

from aml_monitoring.rules.base import BaseRule, RuleContext, RuleResult
from aml_monitoring.rules.geo_mismatch import GeoMismatchRule
from aml_monitoring.rules.high_risk_country import HighRiskCountryRule
from aml_monitoring.rules.high_value import HighValueTransactionRule
from aml_monitoring.rules.network_ring import NetworkRingIndicatorRule
from aml_monitoring.rules.rapid_velocity import RapidVelocityRule
from aml_monitoring.rules.sanctions_keyword import SanctionsKeywordRule
from aml_monitoring.rules.structuring_smurfing import StructuringSmurfingRule


def get_all_rules(config: dict) -> list[BaseRule]:
    """Return enabled rule instances from config."""
    rules: list[BaseRule] = []
    cfg = config.get("rules", {})
    if cfg.get("high_value", {}).get("enabled", True):
        rules.append(HighValueTransactionRule(cfg.get("high_value", {})))
    if cfg.get("rapid_velocity", {}).get("enabled", True):
        rules.append(RapidVelocityRule(cfg.get("rapid_velocity", {})))
    if cfg.get("geo_mismatch", {}).get("enabled", True):
        rules.append(GeoMismatchRule(cfg.get("geo_mismatch", {})))
    if cfg.get("structuring_smurfing", {}).get("enabled", True):
        rules.append(StructuringSmurfingRule(cfg.get("structuring_smurfing", {})))
    if cfg.get("sanctions_keyword", {}).get("enabled", True):
        rules.append(SanctionsKeywordRule(cfg.get("sanctions_keyword", {})))
    if cfg.get("high_risk_country", {}).get("enabled", True):
        rules.append(HighRiskCountryRule(cfg.get("high_risk_country", {})))
    if cfg.get("network_ring", {}).get("enabled", True):
        rules.append(NetworkRingIndicatorRule(cfg.get("network_ring", {})))
    return rules


__all__ = [
    "RuleResult",
    "RuleContext",
    "get_all_rules",
    "HighValueTransactionRule",
    "RapidVelocityRule",
    "GeoMismatchRule",
    "StructuringSmurfingRule",
    "SanctionsKeywordRule",
    "HighRiskCountryRule",
    "NetworkRingIndicatorRule",
]
