"""Case status lifecycle: valid transitions and validation."""

from __future__ import annotations

CASE_STATUS_VALUES = frozenset({"NEW", "INVESTIGATING", "ESCALATED", "CLOSED"})
CASE_PRIORITY_VALUES = frozenset({"LOW", "MEDIUM", "HIGH"})

# Valid (from_status -> to_status). CLOSED cannot transition.
VALID_CASE_TRANSITIONS: dict[str, frozenset[str]] = {
    "NEW": frozenset({"INVESTIGATING", "ESCALATED", "CLOSED"}),
    "INVESTIGATING": frozenset({"ESCALATED", "CLOSED"}),
    "ESCALATED": frozenset({"CLOSED"}),
    "CLOSED": frozenset(),
}


def validate_case_status_transition(current: str, new: str) -> None:
    """Raise ValueError if transition from current to new is invalid."""
    if current not in CASE_STATUS_VALUES:
        raise ValueError(f"Current status must be one of {sorted(CASE_STATUS_VALUES)}")
    if new not in CASE_STATUS_VALUES:
        raise ValueError(f"New status must be one of {sorted(CASE_STATUS_VALUES)}")
    allowed = VALID_CASE_TRANSITIONS.get(current, frozenset())
    if new not in allowed:
        raise ValueError(
            f"Invalid transition: {current} -> {new}. Allowed from {current}: {sorted(allowed) or 'none'}"
        )
