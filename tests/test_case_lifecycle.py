"""Unit tests for case status transition validation."""

import pytest

from aml_monitoring.case_lifecycle import (
    CASE_PRIORITY_VALUES,
    CASE_STATUS_VALUES,
    validate_case_status_transition,
)


def test_valid_transitions_new_to_investigating() -> None:
    validate_case_status_transition("NEW", "INVESTIGATING")


def test_valid_transitions_new_to_escalated() -> None:
    validate_case_status_transition("NEW", "ESCALATED")


def test_valid_transitions_new_to_closed() -> None:
    validate_case_status_transition("NEW", "CLOSED")


def test_valid_transitions_investigating_to_escalated() -> None:
    validate_case_status_transition("INVESTIGATING", "ESCALATED")


def test_valid_transitions_investigating_to_closed() -> None:
    validate_case_status_transition("INVESTIGATING", "CLOSED")


def test_valid_transitions_escalated_to_closed() -> None:
    validate_case_status_transition("ESCALATED", "CLOSED")


def test_invalid_transition_closed_cannot_change() -> None:
    with pytest.raises(ValueError, match="Invalid transition.*CLOSED.*Allowed from CLOSED: none"):
        validate_case_status_transition("CLOSED", "NEW")
    with pytest.raises(ValueError, match="Invalid transition"):
        validate_case_status_transition("CLOSED", "INVESTIGATING")


def test_invalid_transition_new_cannot_go_to_new() -> None:
    with pytest.raises(ValueError, match="Invalid transition"):
        validate_case_status_transition("NEW", "NEW")


def test_invalid_transition_investigating_to_new() -> None:
    with pytest.raises(ValueError, match="Invalid transition.*INVESTIGATING.*NEW"):
        validate_case_status_transition("INVESTIGATING", "NEW")


def test_invalid_status_value() -> None:
    with pytest.raises(ValueError, match="Current status must be one of"):
        validate_case_status_transition("INVALID", "CLOSED")
    with pytest.raises(ValueError, match="New status must be one of"):
        validate_case_status_transition("NEW", "INVALID")


def test_case_status_and_priority_sets() -> None:
    assert {"NEW", "INVESTIGATING", "ESCALATED", "CLOSED"} == CASE_STATUS_VALUES
    assert {"LOW", "MEDIUM", "HIGH"} == CASE_PRIORITY_VALUES
