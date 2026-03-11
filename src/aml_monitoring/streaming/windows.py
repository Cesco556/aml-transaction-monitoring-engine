"""Sliding window aggregations for streaming rules (velocity, structuring)."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class _WindowEvent:
    """Single event within a window."""

    timestamp: float
    amount: float
    counterparty: str | None = None


@dataclass
class WindowStats:
    """Aggregated stats for an account within a time window."""

    transaction_count: int = 0
    total_amount: float = 0.0
    unique_counterparties: int = 0
    counterparties: set[str] = field(default_factory=set)


class SlidingWindow:
    """In-memory sliding window for per-account transaction aggregations.

    Tracks transaction count, total amount, and unique counterparties
    within a configurable time window. TTL-based eviction keeps memory bounded.

    Args:
        window_seconds: Size of the sliding window in seconds.
        max_accounts: Maximum number of accounts to track (LRU eviction).
    """

    def __init__(self, window_seconds: int = 900, max_accounts: int = 100_000) -> None:
        self.window_seconds = window_seconds
        self.max_accounts = max_accounts
        self._events: dict[str, list[_WindowEvent]] = defaultdict(list)
        self._last_evict: float = 0.0

    def add_event(
        self,
        account_id: str,
        amount: float,
        counterparty: str | None = None,
        timestamp: float | None = None,
    ) -> None:
        """Record a transaction event for an account."""
        ts = timestamp if timestamp is not None else time.time()
        self._events[account_id].append(
            _WindowEvent(timestamp=ts, amount=amount, counterparty=counterparty)
        )
        self._maybe_evict(ts)

    def get_stats(self, account_id: str, timestamp: float | None = None) -> WindowStats:
        """Get aggregated stats for an account within the current window."""
        now = timestamp if timestamp is not None else time.time()
        cutoff = now - self.window_seconds
        events = self._events.get(account_id, [])
        # Filter to window
        active = [e for e in events if e.timestamp >= cutoff]
        if len(active) != len(events):
            self._events[account_id] = active

        counterparties: set[str] = set()
        total = 0.0
        for e in active:
            total += e.amount
            if e.counterparty:
                counterparties.add(e.counterparty)

        return WindowStats(
            transaction_count=len(active),
            total_amount=total,
            unique_counterparties=len(counterparties),
            counterparties=counterparties,
        )

    def _maybe_evict(self, now: float) -> None:
        """Evict expired events and enforce max_accounts."""
        if now - self._last_evict < max(self.window_seconds / 4, 5):
            return
        self._last_evict = now
        cutoff = now - self.window_seconds

        # Evict old events
        empty_keys: list[str] = []
        for acct, events in self._events.items():
            self._events[acct] = [e for e in events if e.timestamp >= cutoff]
            if not self._events[acct]:
                empty_keys.append(acct)
        for k in empty_keys:
            del self._events[k]

        # LRU eviction if too many accounts
        if len(self._events) > self.max_accounts:
            # Keep accounts with most recent activity
            by_recency = sorted(
                self._events.keys(),
                key=lambda k: max((e.timestamp for e in self._events[k]), default=0),
                reverse=True,
            )
            for k in by_recency[self.max_accounts :]:
                del self._events[k]

    @property
    def account_count(self) -> int:
        """Number of accounts currently tracked."""
        return len(self._events)

    def clear(self) -> None:
        """Remove all tracked data."""
        self._events.clear()
