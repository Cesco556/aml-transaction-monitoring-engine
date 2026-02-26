"""Tests for audit context (correlation_id and actor traceability)."""

from aml_monitoring.audit_context import (
    get_actor,
    get_audit_context,
    get_correlation_id,
    set_audit_context,
)


def test_set_and_get_context() -> None:
    """When context is set, get_audit_context and get_correlation_id/get_actor return those values."""
    set_audit_context("corr-123", "analyst")
    cid, actor = get_audit_context()
    assert cid == "corr-123"
    assert actor == "analyst"
    assert get_correlation_id() == "corr-123"
    assert get_actor() == "analyst"


def test_get_correlation_id_generated_when_unset() -> None:
    """When correlation_id is not set, get_correlation_id returns a generated UUID."""
    set_audit_context(None, "system")  # no correlation_id set
    cid = get_correlation_id()
    assert cid is not None
    assert len(cid) == 36
    assert cid.count("-") == 4  # UUID format


def test_get_actor_default_system_when_unset() -> None:
    """When actor is not set, get_actor returns 'system'."""
    set_audit_context("x", None)
    assert get_actor() == "system"
    set_audit_context(None, None)
    _, actor = get_audit_context()
    assert actor == "system"


def test_correlation_id_stable_within_context() -> None:
    """Multiple get_correlation_id() calls in same set context return same value."""
    set_audit_context("run-456", "cli")
    assert get_correlation_id() == get_correlation_id()
    assert get_correlation_id() == "run-456"
