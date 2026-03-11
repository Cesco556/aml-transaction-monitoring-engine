"""Alert event bus: simple callback-based pub/sub for alert lifecycle events."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

log = logging.getLogger(__name__)

# Type alias for listeners
AlertListener = Callable[[dict[str, Any]], Any]

_listeners: list[AlertListener] = []


def on_alert_created(callback: AlertListener) -> None:
    """Register a listener for alert creation events."""
    if callback not in _listeners:
        _listeners.append(callback)


def remove_listener(callback: AlertListener) -> None:
    """Remove a previously registered listener."""
    try:
        _listeners.remove(callback)
    except ValueError:
        pass


def emit_alert_created(alert_data: dict[str, Any]) -> None:
    """Notify all registered listeners of a new alert.

    Handles both sync and async callbacks. Async callbacks are scheduled
    on the running event loop if one exists, otherwise called via asyncio.run().
    """
    for listener in _listeners:
        try:
            result = listener(alert_data)
            # If the listener returned a coroutine, schedule it
            if asyncio.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(result)
                except RuntimeError:
                    # No running loop — run synchronously
                    asyncio.run(result)
        except Exception:
            log.exception("Error in alert listener %s", listener.__name__)


def clear_listeners() -> None:
    """Remove all listeners (useful for testing)."""
    _listeners.clear()


def listener_count() -> int:
    """Return number of registered listeners."""
    return len(_listeners)
