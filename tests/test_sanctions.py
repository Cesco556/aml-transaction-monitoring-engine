"""Tests for Phase 4: Advanced Sanctions & Screening module."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aml_monitoring.sanctions.matching import (
    MatchResult,
    exact_match,
    jaro_winkler,
    levenshtein_similarity,
    match_name,
    normalize_name,
    phonetic_match,
)
from aml_monitoring.sanctions.lists import SanctionsEntry, SanctionsList, SanctionsMatch
from aml_monitoring.sanctions.ofac import parse_sdn_csv
from aml_monitoring.sanctions.pep import PEPEntry, PEPList, PEPMatch, screen_pep
from aml_monitoring.rules.sanctions_screening import SanctionsScreeningRule
from aml_monitoring.rules.base import RuleContext


# ===================================================================
# Fixtures
# ===================================================================

SAMPLE_SDN_CSV = Path(__file__).parent.parent / "data" / "sanctions" / "sample_sdn.csv"
SAMPLE_PEP_CSV = Path(__file__).parent.parent / "data" / "sanctions" / "sample_pep.csv"


@pytest.fixture
def sanctions_entries() -> list[SanctionsEntry]:
    return [
        SanctionsEntry(
            name="Ahmad Al-Rashid",
            aliases=["Ahmed Al Rashid", "Ahmad Rashid"],
            entity_type="individual",
            source="OFAC",
            country="SY",
        ),
        SanctionsEntry(
            name="Petromax Trading LLC",
            aliases=["Petromax LLC", "Petromax Trading"],
            entity_type="organization",
            source="OFAC",
            country="IR",
        ),
        SanctionsEntry(
            name="Muhammad Hassan Khan",
            aliases=["Mohammed Hassan Khan", "M. Hassan"],
            entity_type="individual",
            source="OFAC",
            country="PK",
        ),
    ]


@pytest.fixture
def sanctions_list(sanctions_entries: list[SanctionsEntry]) -> SanctionsList:
    sl = SanctionsList(source="test")
    sl.load_entries(sanctions_entries)
    return sl


@pytest.fixture
def pep_entries() -> list[PEPEntry]:
    return [
        PEPEntry(
            name="Vladimir Petrov",
            position="President",
            country="RU",
            risk_level="high",
            aliases=["V. Petrov", "Vlad Petrov"],
        ),
        PEPEntry(
            name="Maria Santos Silva",
            position="Finance Minister",
            country="BR",
            risk_level="high",
            aliases=["Maria Santos"],
        ),
        PEPEntry(
            name="Ahmed Hassan Ibrahim",
            position="Central Bank Governor",
            country="EG",
            risk_level="high",
            aliases=["Ahmed Ibrahim"],
        ),
    ]


@pytest.fixture
def pep_list(pep_entries: list[PEPEntry]) -> PEPList:
    pl = PEPList(source="test")
    pl.load_entries(pep_entries)
    return pl


def _make_ctx(counterparty: str | None = None) -> RuleContext:
    return RuleContext(
        transaction_id=1,
        account_id=1,
        customer_id=1,
        ts=None,
        amount=10000.0,
        currency="USD",
        merchant=None,
        counterparty=counterparty,
        country=None,
        channel=None,
        direction=None,
        session=MagicMock(),
    )


# ===================================================================
# 1. Name normalisation
# ===================================================================


class TestNormalization:
    def test_lowercase_and_strip(self) -> None:
        assert normalize_name("  John SMITH  ") == "john smith"

    def test_remove_punctuation(self) -> None:
        assert normalize_name("O'Brien-Smith") == "o brien smith"

    def test_unicode_accents(self) -> None:
        assert normalize_name("José García") == "jose garcia"

    def test_alias_substitution(self) -> None:
        assert normalize_name("Mohammed") == "muhammad"
        assert normalize_name("Mohammad") == "muhammad"

    def test_company_alias(self) -> None:
        assert normalize_name("Acme Limited") == "acme ltd"
        assert normalize_name("Acme Corporation") == "acme corp"

    def test_empty_string(self) -> None:
        assert normalize_name("") == ""

    def test_whitespace_only(self) -> None:
        assert normalize_name("   ") == ""


# ===================================================================
# 2. Individual matching algorithms
# ===================================================================


class TestExactMatch:
    def test_identical(self) -> None:
        assert exact_match("John Smith", "John Smith") == 1.0

    def test_case_insensitive(self) -> None:
        assert exact_match("john smith", "JOHN SMITH") == 1.0

    def test_different(self) -> None:
        assert exact_match("John Smith", "Jane Doe") == 0.0

    def test_alias_normalised(self) -> None:
        # "Mohammed" → "Muhammad" via alias map
        assert exact_match("Mohammed Ali", "Muhammad Ali") == 1.0


class TestLevenshtein:
    def test_identical(self) -> None:
        assert levenshtein_similarity("John Smith", "John Smith") == 1.0

    def test_similar(self) -> None:
        score = levenshtein_similarity("John Smith", "Jon Smith")
        assert 0.8 < score < 1.0

    def test_very_different(self) -> None:
        score = levenshtein_similarity("John Smith", "ZZZZZ")
        assert score < 0.5

    def test_empty_both(self) -> None:
        assert levenshtein_similarity("", "") == 1.0

    def test_empty_one(self) -> None:
        assert levenshtein_similarity("abc", "") == 0.0


class TestJaroWinkler:
    def test_identical(self) -> None:
        assert jaro_winkler("John Smith", "John Smith") == 1.0

    def test_similar_names(self) -> None:
        score = jaro_winkler("Ahmad Al-Rashid", "Ahmed Al Rashid")
        assert score > 0.8

    def test_different(self) -> None:
        score = jaro_winkler("John", "XXXX")
        assert score < 0.5


class TestPhoneticMatch:
    def test_similar_sounding(self) -> None:
        # "Smith" and "Smyth" should match phonetically
        score = phonetic_match("Smith", "Smyth")
        assert score >= 0.9

    def test_mohammed_muhammad(self) -> None:
        # After normalisation both become "muhammad" — exact phonetic match
        score = phonetic_match("Mohammed", "Muhammad")
        assert score >= 0.9

    def test_completely_different(self) -> None:
        score = phonetic_match("John", "Maria")
        assert score < 0.5

    def test_empty(self) -> None:
        assert phonetic_match("", "test") == 0.0


# ===================================================================
# 3. match_name composite function
# ===================================================================


class TestMatchName:
    def test_exact_hit(self) -> None:
        result = match_name("John Smith", "John Smith", threshold=0.85)
        assert result is not None
        assert result.score == 1.0

    def test_fuzzy_hit(self) -> None:
        result = match_name("Ahmad Al-Rashid", "Ahmed Al Rashid", threshold=0.80)
        assert result is not None
        assert result.score >= 0.80

    def test_below_threshold(self) -> None:
        result = match_name("John Smith", "ZZZZZ YYYY", threshold=0.85)
        assert result is None

    def test_specific_algorithms(self) -> None:
        result = match_name(
            "Mohammed", "Muhammad",
            algorithms=["exact"],
            threshold=0.85,
        )
        # After normalisation both are "muhammad" — exact match
        assert result is not None
        assert result.algorithm == "exact"

    def test_name_variations_mohammed(self) -> None:
        # All Mohammed variants should match Muhammad
        for variant in ["Mohammed", "Mohammad", "Muhammed", "Mohamad", "Mohamed"]:
            result = match_name(variant, "Muhammad", threshold=0.85)
            assert result is not None, f"{variant} should match Muhammad"

    def test_name_variations_company(self) -> None:
        result = match_name("Acme Limited", "Acme Ltd", threshold=0.85)
        assert result is not None


# ===================================================================
# 4. SanctionsList loading and search
# ===================================================================


class TestSanctionsList:
    def test_load_entries(self, sanctions_list: SanctionsList) -> None:
        assert sanctions_list.entry_count == 3

    def test_search_exact(self, sanctions_list: SanctionsList) -> None:
        matches = sanctions_list.search("Ahmad Al-Rashid", threshold=0.85)
        assert len(matches) >= 1
        assert matches[0].score >= 0.85

    def test_search_alias(self, sanctions_list: SanctionsList) -> None:
        matches = sanctions_list.search("Ahmed Al Rashid", threshold=0.85)
        assert len(matches) >= 1

    def test_search_fuzzy(self, sanctions_list: SanctionsList) -> None:
        matches = sanctions_list.search("Mohammed Hassan Khan", threshold=0.80)
        assert len(matches) >= 1

    def test_search_no_match(self, sanctions_list: SanctionsList) -> None:
        matches = sanctions_list.search("Completely Random Name", threshold=0.85)
        assert len(matches) == 0

    def test_search_empty_name(self, sanctions_list: SanctionsList) -> None:
        matches = sanctions_list.search("", threshold=0.85)
        assert matches == []

    def test_load_csv(self, tmp_path: Path) -> None:
        csv_content = (
            "name,aliases,entity_type,source,country,list_date\n"
            'Test Person,Tester|T. Person,individual,OFAC,US,2025-01-01\n'
            'Evil Corp,EC|Evil Corporation,organization,EU,RU,2025-02-01\n'
        )
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content)
        sl = SanctionsList()
        sl.load_csv(csv_file)
        assert sl.entry_count == 2
        assert sl.entries[0].name == "Test Person"
        assert sl.entries[0].aliases == ["Tester", "T. Person"]
        assert sl.entries[1].entity_type == "organization"

    def test_load_json(self, tmp_path: Path) -> None:
        data = [
            {
                "name": "Test Person",
                "aliases": ["Tester"],
                "entity_type": "individual",
                "source": "UN",
                "country": "US",
            },
        ]
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(data))
        sl = SanctionsList()
        sl.load_json(json_file)
        assert sl.entry_count == 1
        assert sl.entries[0].source == "UN"

    def test_status(self, sanctions_list: SanctionsList) -> None:
        status = sanctions_list.status()
        assert status["source"] == "test"
        assert status["entry_count"] == 3
        assert status["loaded_at"] is not None

    def test_search_sorted_by_score(self, sanctions_list: SanctionsList) -> None:
        # Add a lower-confidence entry
        sanctions_list.entries.append(
            SanctionsEntry(name="Ahmad Rasheed", aliases=[], source="test")
        )
        matches = sanctions_list.search("Ahmad Rashid", threshold=0.70)
        if len(matches) > 1:
            assert matches[0].score >= matches[1].score


# ===================================================================
# 5. OFAC SDN parser
# ===================================================================


class TestOFACParser:
    def test_parse_sample_sdn(self) -> None:
        if not SAMPLE_SDN_CSV.exists():
            pytest.skip("sample_sdn.csv not found")
        entries = parse_sdn_csv(SAMPLE_SDN_CSV)
        assert len(entries) == 20
        # Check first entry
        first = entries[0]
        assert "AHMAD" in first.name.upper()
        assert first.source == "OFAC"
        assert first.entity_type == "individual"

    def test_parse_entity_types(self) -> None:
        if not SAMPLE_SDN_CSV.exists():
            pytest.skip("sample_sdn.csv not found")
        entries = parse_sdn_csv(SAMPLE_SDN_CSV)
        individuals = [e for e in entries if e.entity_type == "individual"]
        organizations = [e for e in entries if e.entity_type == "organization"]
        assert len(individuals) > 0
        assert len(organizations) > 0

    def test_parse_aliases(self) -> None:
        if not SAMPLE_SDN_CSV.exists():
            pytest.skip("sample_sdn.csv not found")
        entries = parse_sdn_csv(SAMPLE_SDN_CSV)
        has_aliases = any(len(e.aliases) > 0 for e in entries)
        assert has_aliases

    def test_parse_csv_with_header(self, tmp_path: Path) -> None:
        csv_content = (
            "ent_num,sdn_name,sdn_type,program,title,remarks,country,aliases\n"
            "99999,Test Sanctioned Person,individual,SDGT,,DOB 01 Jan 1990,US,TSP|Test Person\n"
        )
        f = tmp_path / "test_sdn.csv"
        f.write_text(csv_content)
        entries = parse_sdn_csv(f)
        assert len(entries) == 1
        assert entries[0].name == "Test Sanctioned Person"
        assert "TSP" in entries[0].aliases


# ===================================================================
# 6. PEP screening
# ===================================================================


class TestPEPScreening:
    def test_load_entries(self, pep_list: PEPList) -> None:
        assert pep_list.entry_count == 3

    def test_search_exact(self, pep_list: PEPList) -> None:
        matches = pep_list.search("Vladimir Petrov", threshold=0.85)
        assert len(matches) >= 1
        assert matches[0].entry.position == "President"

    def test_search_alias(self, pep_list: PEPList) -> None:
        matches = pep_list.search("Vlad Petrov", threshold=0.80)
        assert len(matches) >= 1

    def test_search_with_country_filter(self, pep_list: PEPList) -> None:
        matches = pep_list.search("Vladimir Petrov", country="RU", threshold=0.85)
        assert len(matches) >= 1
        # Filter by wrong country
        matches_br = pep_list.search("Vladimir Petrov", country="BR", threshold=0.85)
        assert len(matches_br) == 0

    def test_search_no_match(self, pep_list: PEPList) -> None:
        matches = pep_list.search("Nobody Known", threshold=0.85)
        assert matches == []

    def test_screen_pep_convenience(self, pep_list: PEPList) -> None:
        matches = screen_pep("Maria Santos", pep_list=pep_list, threshold=0.80)
        assert len(matches) >= 1

    def test_load_csv(self) -> None:
        if not SAMPLE_PEP_CSV.exists():
            pytest.skip("sample_pep.csv not found")
        pl = PEPList()
        pl.load_csv(SAMPLE_PEP_CSV)
        assert pl.entry_count == 10

    def test_status(self, pep_list: PEPList) -> None:
        status = pep_list.status()
        assert status["entry_count"] == 3


# ===================================================================
# 7. Enhanced sanctions screening rule
# ===================================================================


class TestSanctionsScreeningRule:
    def test_keyword_fallback(self) -> None:
        """When no lists are configured, falls back to keyword matching."""
        rule = SanctionsScreeningRule({
            "enabled": True,
            "keywords": ["sanctioned", "blocked"],
            "severity": "high",
            "score_delta": 30.0,
            "screening": {"enabled": True, "lists": {}},
        })
        ctx = _make_ctx(counterparty="Sanctioned Entity Inc")
        results = rule.evaluate(ctx)
        assert len(results) >= 1
        assert "keyword" in results[0].evidence_fields.get("method", "")

    def test_no_counterparty(self) -> None:
        rule = SanctionsScreeningRule({
            "enabled": True,
            "keywords": ["sanctioned"],
            "screening": {"enabled": True, "lists": {}},
        })
        ctx = _make_ctx(counterparty=None)
        results = rule.evaluate(ctx)
        assert results == []

    def test_disabled(self) -> None:
        rule = SanctionsScreeningRule({"enabled": False})
        ctx = _make_ctx(counterparty="Sanctioned Entity")
        results = rule.evaluate(ctx)
        assert results == []

    def test_fuzzy_screening_with_entries(self) -> None:
        """Test fuzzy matching when sanctions entries are loaded directly."""
        rule = SanctionsScreeningRule({
            "enabled": True,
            "severity": "high",
            "score_delta": 30.0,
            "screening": {
                "enabled": True,
                "min_match_threshold": 0.80,
                "algorithms": ["exact", "jaro_winkler", "levenshtein", "phonetic"],
                "lists": {},
            },
        })
        # Manually load a sanctions list into the rule
        from aml_monitoring.sanctions.lists import SanctionsList, SanctionsEntry

        sl = SanctionsList(source="test")
        sl.load_entries([
            SanctionsEntry(
                name="Ahmad Al-Rashid",
                aliases=["Ahmed Al Rashid"],
                source="OFAC",
                country="SY",
            ),
        ])
        rule._sanctions_lists = [sl]

        ctx = _make_ctx(counterparty="Ahmed Al Rashid")
        results = rule.evaluate(ctx)
        assert len(results) >= 1
        assert results[0].evidence_fields["match_confidence"] >= 0.80

    def test_rule_id(self) -> None:
        rule = SanctionsScreeningRule({"enabled": True})
        assert rule.rule_id == "SanctionsScreening"

    def test_pep_screening_integration(self) -> None:
        """Test PEP screening within the rule."""
        rule = SanctionsScreeningRule({
            "enabled": True,
            "severity": "high",
            "score_delta": 30.0,
            "screening": {
                "enabled": True,
                "min_match_threshold": 0.85,
                "algorithms": ["exact", "jaro_winkler", "levenshtein", "phonetic"],
                "lists": {},
            },
            "pep": {
                "enabled": True,
                "min_match_threshold": 0.80,
            },
        })
        # Manually load PEP list
        from aml_monitoring.sanctions.pep import PEPList, PEPEntry

        pl = PEPList(source="test")
        pl.load_entries([
            PEPEntry(
                name="Vladimir Petrov",
                position="President",
                country="RU",
                risk_level="high",
            ),
        ])
        rule._pep_list = pl

        ctx = _make_ctx(counterparty="Vladimir Petrov")
        results = rule.evaluate(ctx)
        assert len(results) >= 1
        assert any("PEP" in r.reason for r in results)


# ===================================================================
# 8. Edge cases
# ===================================================================


class TestEdgeCases:
    def test_empty_name_match(self) -> None:
        result = match_name("", "John Smith", threshold=0.0)
        # Empty query should not match
        assert result is None or result.score == 0.0

    def test_unicode_characters(self) -> None:
        result = match_name("José García", "Jose Garcia", threshold=0.85)
        assert result is not None
        assert result.score >= 0.85

    def test_very_long_name(self) -> None:
        long_name = "A" * 500
        target = "A" * 500
        result = match_name(long_name, target, threshold=0.85)
        assert result is not None
        assert result.score == 1.0

    def test_special_characters(self) -> None:
        score = levenshtein_similarity("Al-Qaeda", "Al Qaeda")
        assert score > 0.8

    def test_single_character_names(self) -> None:
        result = match_name("A", "A", threshold=0.85)
        assert result is not None

    def test_numbers_in_names(self) -> None:
        # Some entities have numbers
        score = exact_match("Entity 123", "Entity 123")
        assert score == 1.0

    def test_mixed_scripts(self) -> None:
        # Normalise should handle gracefully
        name = normalize_name("Müller Straße")
        assert "muller" in name

    def test_sanctions_entry_all_names(self) -> None:
        entry = SanctionsEntry(name="Primary", aliases=["Alias1", "Alias2"])
        assert entry.all_names == ["Primary", "Alias1", "Alias2"]

    def test_pep_entry_all_names(self) -> None:
        entry = PEPEntry(name="Primary", aliases=["Alias1"])
        assert entry.all_names == ["Primary", "Alias1"]


# ===================================================================
# 9. Graceful fallback
# ===================================================================


class TestGracefulFallback:
    def test_keyword_fallback_no_fuzzy_lists(self) -> None:
        """Even with fuzzy module available, falls back to keywords if
        no sanctions lists are loaded."""
        rule = SanctionsScreeningRule({
            "enabled": True,
            "keywords": ["blocked"],
            "severity": "high",
            "score_delta": 30.0,
            "screening": {"enabled": True, "lists": {}},
            "pep": {"enabled": False},
        })
        # No lists loaded → should use keyword fallback
        assert len(rule._sanctions_lists) == 0
        ctx = _make_ctx(counterparty="Blocked Entity")
        results = rule.evaluate(ctx)
        assert len(results) >= 1
        assert results[0].evidence_fields.get("method") == "keyword_fallback"

    def test_no_match_keyword_fallback(self) -> None:
        rule = SanctionsScreeningRule({
            "enabled": True,
            "keywords": ["sanctioned"],
            "screening": {"enabled": True, "lists": {}},
            "pep": {"enabled": False},
        })
        ctx = _make_ctx(counterparty="Normal Business LLC")
        results = rule.evaluate(ctx)
        assert results == []
