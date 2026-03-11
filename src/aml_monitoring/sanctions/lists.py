"""Sanctions list management — load, store, and fuzzy-search entries."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from aml_monitoring.sanctions.matching import (
    DEFAULT_ALGORITHMS,
    DEFAULT_THRESHOLD,
    MatchResult,
    match_name,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SanctionsEntry:
    """A single entity on a sanctions list."""

    name: str
    aliases: list[str] = field(default_factory=list)
    entity_type: str = "individual"  # individual | organization
    source: str = "unknown"  # OFAC | EU | UN | custom
    country: str = ""
    list_date: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def all_names(self) -> list[str]:
        """Primary name + aliases."""
        return [self.name] + self.aliases


@dataclass(frozen=True)
class SanctionsMatch:
    """A match result referencing the original sanctions entry."""

    entry: SanctionsEntry
    score: float
    algorithm: str
    matched_alias: str  # the name/alias that produced the match


# ---------------------------------------------------------------------------
# SanctionsList
# ---------------------------------------------------------------------------


class SanctionsList:
    """Load and manage a set of sanctions entries with fuzzy search."""

    def __init__(self, *, source: str = "custom") -> None:
        self.source = source
        self.entries: list[SanctionsEntry] = []
        self._loaded_at: datetime | None = None
        self._file_path: str | None = None

    # -- loaders --------------------------------------------------------

    def load_csv(self, filepath: str | Path) -> None:
        """Load entries from a CSV file.

        Expected columns (case-insensitive, flexible):
            name, aliases (pipe-separated), entity_type, source, country, list_date
        """
        filepath = Path(filepath)
        with open(filepath, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                # Normalise keys to lowercase
                r = {k.strip().lower(): v.strip() for k, v in row.items()}
                aliases_raw = r.get("aliases", "")
                aliases = [a.strip() for a in aliases_raw.split("|") if a.strip()]
                self.entries.append(
                    SanctionsEntry(
                        name=r.get("name", ""),
                        aliases=aliases,
                        entity_type=r.get("entity_type", "individual"),
                        source=r.get("source", self.source),
                        country=r.get("country", ""),
                        list_date=r.get("list_date", ""),
                    )
                )
        self._loaded_at = datetime.now(tz=UTC)
        self._file_path = str(filepath)

    def load_json(self, filepath: str | Path) -> None:
        """Load entries from a JSON file (list of objects)."""
        filepath = Path(filepath)
        with open(filepath, encoding="utf-8") as fh:
            data = json.load(fh)
        for item in data:
            self.entries.append(
                SanctionsEntry(
                    name=item.get("name", ""),
                    aliases=item.get("aliases", []),
                    entity_type=item.get("entity_type", "individual"),
                    source=item.get("source", self.source),
                    country=item.get("country", ""),
                    list_date=item.get("list_date", ""),
                    extra=item.get("extra", {}),
                )
            )
        self._loaded_at = datetime.now(tz=UTC)
        self._file_path = str(filepath)

    def load_entries(self, entries: list[SanctionsEntry]) -> None:
        """Load entries directly (for testing)."""
        self.entries.extend(entries)
        self._loaded_at = datetime.now(tz=UTC)

    # -- search ---------------------------------------------------------

    def search(
        self,
        name: str,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        algorithms: list[str] | None = None,
    ) -> list[SanctionsMatch]:
        """Fuzzy-search *name* against all entries and their aliases.

        Returns list of :class:`SanctionsMatch` sorted by score descending.
        """
        if not name or not name.strip():
            return []

        algos = algorithms or DEFAULT_ALGORITHMS
        matches: list[SanctionsMatch] = []
        for entry in self.entries:
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
                    SanctionsMatch(
                        entry=entry,
                        score=round(best_score, 4),
                        algorithm=best_algo,
                        matched_alias=best_alias,
                    )
                )
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches

    # -- status ---------------------------------------------------------

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def loaded_at(self) -> datetime | None:
        return self._loaded_at

    @property
    def file_path(self) -> str | None:
        return self._file_path

    def status(self) -> dict[str, Any]:
        """Return a status dict for CLI / API consumption."""
        return {
            "source": self.source,
            "entry_count": self.entry_count,
            "loaded_at": self._loaded_at.isoformat() if self._loaded_at else None,
            "file_path": self._file_path,
        }
