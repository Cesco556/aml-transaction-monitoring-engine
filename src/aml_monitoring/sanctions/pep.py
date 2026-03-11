"""Politically Exposed Persons (PEP) screening framework."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aml_monitoring.sanctions.matching import (
    DEFAULT_ALGORITHMS,
    DEFAULT_THRESHOLD,
    match_name,
)


@dataclass
class PEPEntry:
    """A single Politically Exposed Person entry."""

    name: str
    position: str = ""
    country: str = ""
    risk_level: str = "high"  # low | medium | high
    source: str = "custom"
    aliases: list[str] = field(default_factory=list)

    @property
    def all_names(self) -> list[str]:
        return [self.name] + self.aliases


@dataclass(frozen=True)
class PEPMatch:
    """Result of a PEP screening match."""

    entry: PEPEntry
    score: float
    algorithm: str
    matched_alias: str


class PEPList:
    """Load and manage PEP entries with fuzzy search."""

    def __init__(self, *, source: str = "custom") -> None:
        self.source = source
        self.entries: list[PEPEntry] = []
        self._loaded_at: datetime | None = None
        self._file_path: str | None = None

    def load_csv(self, filepath: str | Path) -> None:
        """Load PEP entries from CSV.

        Expected columns: name, position, country, risk_level, source, aliases (pipe-separated)
        """
        filepath = Path(filepath)
        with open(filepath, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                r = {k.strip().lower(): v.strip() for k, v in row.items()}
                aliases_raw = r.get("aliases", "")
                aliases = [a.strip() for a in aliases_raw.split("|") if a.strip()]
                self.entries.append(
                    PEPEntry(
                        name=r.get("name", ""),
                        position=r.get("position", ""),
                        country=r.get("country", ""),
                        risk_level=r.get("risk_level", "high"),
                        source=r.get("source", self.source),
                        aliases=aliases,
                    )
                )
        self._loaded_at = datetime.now(tz=UTC)
        self._file_path = str(filepath)

    def load_entries(self, entries: list[PEPEntry]) -> None:
        """Load entries directly (for testing)."""
        self.entries.extend(entries)
        self._loaded_at = datetime.now(tz=UTC)

    def search(
        self,
        name: str,
        *,
        country: str | None = None,
        threshold: float = DEFAULT_THRESHOLD,
        algorithms: list[str] | None = None,
    ) -> list[PEPMatch]:
        """Fuzzy-search name against PEP entries.

        If *country* is provided, results are filtered to entries matching
        that country (case-insensitive).
        """
        if not name or not name.strip():
            return []

        algos = algorithms or DEFAULT_ALGORITHMS
        matches: list[PEPMatch] = []

        for entry in self.entries:
            # Country filter
            if country and entry.country.lower() != country.lower():
                continue

            best_score = 0.0
            best_algo = ""
            best_alias = ""
            for candidate in entry.all_names:
                result = match_name(name, candidate, algorithms=algos, threshold=threshold)
                if result and result.score > best_score:
                    best_score = result.score
                    best_algo = result.algorithm
                    best_alias = candidate
            if best_score >= threshold:
                matches.append(
                    PEPMatch(
                        entry=entry,
                        score=round(best_score, 4),
                        algorithm=best_algo,
                        matched_alias=best_alias,
                    )
                )

        matches.sort(key=lambda m: m.score, reverse=True)
        return matches

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def loaded_at(self) -> datetime | None:
        return self._loaded_at

    def status(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "entry_count": self.entry_count,
            "loaded_at": self._loaded_at.isoformat() if self._loaded_at else None,
            "file_path": self._file_path,
        }


def screen_pep(
    name: str,
    *,
    pep_list: PEPList,
    country: str | None = None,
    threshold: float = 0.80,
    algorithms: list[str] | None = None,
) -> list[PEPMatch]:
    """Convenience function: screen a name against a PEP list."""
    return pep_list.search(
        name, country=country, threshold=threshold, algorithms=algorithms
    )
