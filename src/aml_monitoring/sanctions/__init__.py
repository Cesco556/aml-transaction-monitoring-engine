"""Advanced sanctions screening and fuzzy name matching."""

from __future__ import annotations

from aml_monitoring.sanctions.matching import MatchResult, match_name
from aml_monitoring.sanctions.lists import SanctionsEntry, SanctionsList, SanctionsMatch

__all__ = [
    "MatchResult",
    "SanctionsEntry",
    "SanctionsList",
    "SanctionsMatch",
    "match_name",
]
