"""Alert deduplication: prevent duplicate alerts within a configurable time window."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class _DedupEntry:
    """Internal entry tracking when a key was first seen."""

    timestamp: float


class AlertDeduplicator:
    """In-memory deduplication with TTL-based expiry.

    Keys are tuples like (transaction_id, rule_id) or (account_id, rule_id, window_key).
    If a key has been seen within ``window_seconds``, ``is_duplicate`` returns True.
    """

    def __init__(self, window_seconds: int = 3600) -> None:
        self.window_seconds = window_seconds
        self._seen: dict[tuple, _DedupEntry] = {}
        self._last_evict: float = 0.0

    def is_duplicate(self, key: tuple) -> bool:
        """Return True if *key* was already recorded within the dedup window."""
        now = time.monotonic()
        self._maybe_evict(now)

        entry = self._seen.get(key)
        if entry is not None and (now - entry.timestamp) < self.window_seconds:
            return True
        # Record (or refresh) the key
        self._seen[key] = _DedupEntry(timestamp=now)
        return False

    def _maybe_evict(self, now: float) -> None:
        """Evict expired entries periodically to bound memory."""
        if now - self._last_evict < max(self.window_seconds / 4, 10):
            return
        self._last_evict = now
        cutoff = now - self.window_seconds
        expired = [k for k, v in self._seen.items() if v.timestamp < cutoff]
        for k in expired:
            del self._seen[k]

    @property
    def size(self) -> int:
        """Number of tracked keys (including possibly expired)."""
        return len(self._seen)

    def clear(self) -> None:
        """Remove all tracked keys."""
        self._seen.clear()
