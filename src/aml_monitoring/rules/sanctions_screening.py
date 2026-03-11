"""Enhanced sanctions & PEP screening rule with fuzzy name matching.

Replaces the naive keyword-based approach with proper fuzzy matching when the
sanctions module is available.  Falls back gracefully to keyword matching
if dependencies (rapidfuzz, jellyfish) are not installed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aml_monitoring.rules.base import BaseRule, RuleContext
from aml_monitoring.schemas import RuleResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try to import the fuzzy sanctions module
# ---------------------------------------------------------------------------

try:
    from aml_monitoring.sanctions.lists import SanctionsEntry, SanctionsList
    from aml_monitoring.sanctions.pep import PEPList, screen_pep
    from aml_monitoring.sanctions.ofac import parse_sdn_csv

    _HAS_SANCTIONS_MODULE = True
except ImportError:  # pragma: no cover
    _HAS_SANCTIONS_MODULE = False


class SanctionsScreeningRule(BaseRule):
    """Fuzzy sanctions + PEP screening rule.

    When the sanctions module is available, performs proper fuzzy matching
    against loaded sanctions lists and PEP lists.  Falls back to simple
    keyword matching otherwise.
    """

    rule_id = "SanctionsScreening"

    def __init__(self, config: dict) -> None:
        self.enabled = config.get("enabled", True)

        # Fuzzy matching configuration
        screening_cfg = config.get("screening", {})
        self.threshold = float(screening_cfg.get("min_match_threshold", 0.85))
        self.algorithms = screening_cfg.get(
            "algorithms", ["exact", "jaro_winkler", "levenshtein", "phonetic"]
        )

        # PEP configuration
        pep_cfg = config.get("pep", {})
        self.pep_threshold = float(pep_cfg.get("min_match_threshold", 0.80))
        self.pep_enabled = pep_cfg.get("enabled", True)

        # Keyword fallback
        self.keywords = [k.lower() for k in config.get("keywords", [])]
        self.severity = str(config.get("severity", "high"))
        self.score_delta = float(config.get("score_delta", 30.0))

        # Initialise lists
        self._sanctions_lists: list[SanctionsList] = []
        self._pep_list: PEPList | None = None
        self._fuzzy_available = _HAS_SANCTIONS_MODULE

        if self._fuzzy_available:
            self._load_lists(config)

    def _load_lists(self, config: dict) -> None:
        """Load sanctions and PEP lists from config paths."""
        screening_cfg = config.get("screening", {})
        lists_cfg = screening_cfg.get("lists", {})

        for list_name, list_conf in lists_cfg.items():
            if not list_conf.get("enabled", True):
                continue
            path = list_conf.get("path", "")
            fmt = list_conf.get("format", "csv")
            if not path or not Path(path).exists():
                logger.debug("Sanctions list %s: path %r not found, skipping", list_name, path)
                continue
            try:
                sl = SanctionsList(source=list_name)
                if fmt == "ofac_csv":
                    entries = parse_sdn_csv(path)
                    sl.load_entries(entries)
                elif fmt == "json":
                    sl.load_json(path)
                else:
                    sl.load_csv(path)
                self._sanctions_lists.append(sl)
                logger.info(
                    "Loaded sanctions list %s: %d entries from %s",
                    list_name, sl.entry_count, path,
                )
            except Exception:
                logger.warning("Failed to load sanctions list %s from %s", list_name, path, exc_info=True)

        # PEP list
        pep_cfg = config.get("pep", {})
        if pep_cfg.get("enabled", True):
            pep_path = pep_cfg.get("path", "")
            if pep_path and Path(pep_path).exists():
                try:
                    self._pep_list = PEPList(source="pep")
                    self._pep_list.load_csv(pep_path)
                    logger.info("Loaded PEP list: %d entries from %s", self._pep_list.entry_count, pep_path)
                except Exception:
                    logger.warning("Failed to load PEP list from %s", pep_path, exc_info=True)
                    self._pep_list = None

    def evaluate(self, ctx: RuleContext) -> list[RuleResult]:
        """Screen counterparty and customer name against sanctions + PEP."""
        if not self.enabled:
            return []

        results: list[RuleResult] = []
        names_to_check: list[tuple[str, str]] = []  # (name, label)

        if ctx.counterparty:
            names_to_check.append((ctx.counterparty, "counterparty"))

        # Also check customer name if available via extra context
        # (RuleContext doesn't have customer_name by default, but we can
        # check counterparty which is the primary use case)

        if self._fuzzy_available and self._sanctions_lists:
            results.extend(self._fuzzy_screen(names_to_check))
        else:
            results.extend(self._keyword_fallback(names_to_check))

        # PEP screening
        if self._fuzzy_available and self._pep_list and self.pep_enabled:
            results.extend(self._pep_screen(names_to_check))

        return results

    def _fuzzy_screen(self, names: list[tuple[str, str]]) -> list[RuleResult]:
        """Screen names against sanctions lists using fuzzy matching."""
        results: list[RuleResult] = []
        for name, label in names:
            for sl in self._sanctions_lists:
                matches = sl.search(
                    name,
                    threshold=self.threshold,
                    algorithms=self.algorithms,
                )
                for m in matches:
                    evidence: dict[str, Any] = {
                        label: name,
                        "matched_name": m.matched_alias,
                        "match_confidence": m.score,
                        "match_algorithm": m.algorithm,
                        "sanctions_list": sl.source,
                        "entity_type": m.entry.entity_type,
                        "source": m.entry.source,
                        "country": m.entry.country,
                    }
                    results.append(
                        RuleResult(
                            rule_id=self.rule_id,
                            severity=self.severity,
                            reason=(
                                f"{label.title()} {name!r} matches sanctions entry "
                                f"{m.matched_alias!r} ({m.algorithm}, "
                                f"confidence={m.score:.2%})"
                            ),
                            evidence_fields=evidence,
                            score_delta=self.score_delta,
                        )
                    )
        return results

    def _pep_screen(self, names: list[tuple[str, str]]) -> list[RuleResult]:
        """Screen names against the PEP list."""
        results: list[RuleResult] = []
        if not self._pep_list:
            return results

        for name, label in names:
            matches = self._pep_list.search(
                name,
                threshold=self.pep_threshold,
                algorithms=self.algorithms,
            )
            for m in matches:
                evidence: dict[str, Any] = {
                    label: name,
                    "matched_name": m.matched_alias,
                    "match_confidence": m.score,
                    "match_algorithm": m.algorithm,
                    "pep_position": m.entry.position,
                    "pep_country": m.entry.country,
                    "pep_risk_level": m.entry.risk_level,
                }
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        severity="high" if m.entry.risk_level == "high" else "medium",
                        reason=(
                            f"{label.title()} {name!r} matches PEP entry "
                            f"{m.matched_alias!r} — {m.entry.position} "
                            f"({m.algorithm}, confidence={m.score:.2%})"
                        ),
                        evidence_fields=evidence,
                        score_delta=self.score_delta * 0.8,  # slightly lower for PEP
                    )
                )
        return results

    def _keyword_fallback(self, names: list[tuple[str, str]]) -> list[RuleResult]:
        """Fall back to basic keyword matching when fuzzy module unavailable."""
        results: list[RuleResult] = []
        for name, label in names:
            name_lower = name.lower()
            for kw in self.keywords:
                if kw in name_lower:
                    evidence = {
                        label: name,
                        "keyword": kw,
                        "method": "keyword_fallback",
                    }
                    results.append(
                        RuleResult(
                            rule_id=self.rule_id,
                            severity=self.severity,
                            reason=f"{label.title()} name matches sanctions keyword: {kw!r}",
                            evidence_fields=evidence,
                            score_delta=self.score_delta,
                        )
                    )
                    break  # One hit per name is enough for keyword
        return results
