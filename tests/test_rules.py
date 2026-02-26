"""Unit tests for detection rules."""

from datetime import UTC, datetime
from types import SimpleNamespace

from aml_monitoring.rules.base import RuleContext
from aml_monitoring.rules.high_risk_country import HighRiskCountryRule
from aml_monitoring.rules.high_value import HighValueTransactionRule
from aml_monitoring.rules.sanctions_keyword import SanctionsKeywordRule


def _ctx(
    amount: float = 1000, counterparty: str | None = None, country: str | None = "USA"
) -> RuleContext:
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


def test_high_value_above_threshold() -> None:
    rule = HighValueTransactionRule({"threshold_amount": 10_000})
    results = rule.evaluate(_ctx(amount=15_000))
    assert len(results) == 1
    assert results[0].rule_id == "HighValueTransaction"
    assert results[0].score_delta == 25.0


def test_high_value_below_threshold() -> None:
    rule = HighValueTransactionRule({"threshold_amount": 10_000})
    results = rule.evaluate(_ctx(amount=5_000))
    assert len(results) == 0


def test_sanctions_keyword_match() -> None:
    rule = SanctionsKeywordRule({"keywords": ["sanctioned", "ofac"]})
    results = rule.evaluate(_ctx(counterparty="Acme sanctioned entity"))
    assert len(results) == 1
    assert results[0].rule_id == "SanctionsKeywordMatch"


def test_sanctions_keyword_no_match() -> None:
    rule = SanctionsKeywordRule({"keywords": ["sanctioned"]})
    results = rule.evaluate(_ctx(counterparty="Acme Corp"))
    assert len(results) == 0


def test_high_risk_country_match() -> None:
    rule = HighRiskCountryRule({"countries": ["IR", "XX"]})
    results = rule.evaluate(_ctx(country="IR"))
    assert len(results) == 1
    assert results[0].rule_id == "HighRiskCountry"


def test_high_risk_country_no_match() -> None:
    rule = HighRiskCountryRule({"countries": ["IR"]})
    results = rule.evaluate(_ctx(country="USA"))
    assert len(results) == 0


def test_sanctions_evidence_has_list_version_and_effective_date() -> None:
    rule = SanctionsKeywordRule(
        {
            "keywords": ["sanctioned"],
            "list_version": "2.0",
            "effective_date": "2026-02-01",
        }
    )
    results = rule.evaluate(_ctx(counterparty="sanctioned entity"))
    assert len(results) == 1
    assert results[0].evidence_fields is not None
    assert results[0].evidence_fields.get("list_version") == "2.0"
    assert results[0].evidence_fields.get("effective_date") == "2026-02-01"


def test_high_risk_country_evidence_has_list_version_and_effective_date() -> None:
    rule = HighRiskCountryRule(
        {
            "countries": ["IR"],
            "list_version": "1.0",
            "effective_date": "2026-01-01",
        }
    )
    results = rule.evaluate(_ctx(country="IR"))
    assert len(results) == 1
    assert results[0].evidence_fields is not None
    assert results[0].evidence_fields.get("list_version") == "1.0"
    assert results[0].evidence_fields.get("effective_date") == "2026-01-01"
