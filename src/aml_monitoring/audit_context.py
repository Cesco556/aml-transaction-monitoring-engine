"""Audit context: correlation_id and actor for traceability (CLI run or API request)."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

_correlation_id: ContextVar[str | None] = ContextVar("audit_correlation_id", default=None)
_actor: ContextVar[str | None] = ContextVar("audit_actor", default=None)


def set_audit_context(correlation_id: str | None, actor: str | None = None) -> None:
    """Set correlation_id and actor for the current context (e.g. CLI run or API request)."""
    _correlation_id.set(correlation_id)
    _actor.set(actor)


def set_actor(actor: str) -> None:
    """Set only the actor for the current context (e.g. after API key auth). Leaves correlation_id unchanged."""
    _actor.set(actor)


def get_audit_context() -> tuple[str, str]:
    """Return (correlation_id, actor). Generates correlation_id if not set; actor defaults to 'system'."""
    cid = _correlation_id.get()
    if cid is None:
        cid = str(uuid.uuid4())
    act = _actor.get()
    if act is None:
        act = "system"
    return cid, act


def get_correlation_id() -> str:
    """Return current correlation_id, generating one if not set."""
    cid, _ = get_audit_context()
    return cid


def get_actor() -> str:
    """Return current actor, default 'system' if not set."""
    _, act = get_audit_context()
    return act
