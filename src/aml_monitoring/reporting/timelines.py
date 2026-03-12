"""Regulatory timeline tracking for SAR filing deadlines."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from aml_monitoring.config import get_config
from aml_monitoring.models import Alert, Case, CaseItem


# Regulation deadline configurations (days)
REGULATION_DEADLINES: dict[str, dict[str, int]] = {
    "fincen": {"initial": 30, "extended": 60},
    "fca": {"initial": 15, "extended": 30},       # UK FCA
    "amld": {"initial": 30, "extended": 45},       # EU AMLD
}


def compute_filing_deadline(
    alert_created_at: datetime,
    regulation: str = "fincen",
    extended: bool = False,
) -> datetime:
    """Compute regulatory filing deadline from alert detection date.

    Args:
        alert_created_at: When the alert was first raised.
        regulation: Regulation name (fincen, fca, amld).
        extended: Whether to use extended deadline.

    Returns:
        Filing deadline datetime.
    """
    reg = REGULATION_DEADLINES.get(regulation)
    if reg is None:
        raise ValueError(f"Unknown regulation: {regulation}. Known: {list(REGULATION_DEADLINES)}")

    key = "extended" if extended else "initial"
    days = reg[key]
    return alert_created_at + timedelta(days=days)


@dataclass
class OverdueCase:
    """A case that has exceeded its regulatory filing deadline."""

    case_id: int
    case_status: str
    earliest_alert_at: datetime
    deadline: datetime
    days_overdue: int
    alert_count: int


def get_overdue_cases(
    session,
    regulation: str = "fincen",
    config_path: str | None = None,
) -> list[OverdueCase]:
    """Find cases past their filing deadline.

    Only considers non-CLOSED cases with linked alerts.
    """
    config = get_config(config_path)
    sar_cfg = config.get("reporting", {}).get("sar", {})
    reg = sar_cfg.get("regulation", regulation)

    now = datetime.now(UTC)

    # Get all open cases with their earliest alert creation time
    stmt = (
        select(
            Case.id,
            Case.status,
            func.min(Alert.created_at).label("earliest_alert"),
            func.count(Alert.id).label("alert_count"),
        )
        .join(CaseItem, CaseItem.case_id == Case.id)
        .join(Alert, Alert.id == CaseItem.alert_id)
        .where(Case.status != "CLOSED")
        .where(CaseItem.alert_id.isnot(None))
        .group_by(Case.id, Case.status)
    )

    results = session.execute(stmt).all()
    overdue: list[OverdueCase] = []

    for row in results:
        case_id, status, earliest_alert, alert_count = row
        if earliest_alert is None:
            continue
        # Ensure timezone-aware
        if earliest_alert.tzinfo is None:
            earliest_alert = earliest_alert.replace(tzinfo=UTC)
        deadline = compute_filing_deadline(earliest_alert, regulation=reg)
        if now > deadline:
            days = (now - deadline).days
            overdue.append(
                OverdueCase(
                    case_id=case_id,
                    case_status=status,
                    earliest_alert_at=earliest_alert,
                    deadline=deadline,
                    days_overdue=days,
                    alert_count=alert_count,
                )
            )

    overdue.sort(key=lambda o: o.days_overdue, reverse=True)
    return overdue


@dataclass
class TimelineMetrics:
    """Aggregate metrics for regulatory timeline compliance."""

    avg_investigation_days: float | None = None
    avg_time_to_file_days: float | None = None
    overdue_count: int = 0
    total_cases: int = 0
    closed_cases: int = 0
    open_cases: int = 0


def get_timeline_metrics(
    session,
    regulation: str = "fincen",
    config_path: str | None = None,
) -> TimelineMetrics:
    """Compute timeline compliance metrics across all cases.

    - avg_investigation_days: average time from case creation to CLOSED (for closed cases).
    - avg_time_to_file_days: average time from earliest alert to case closure.
    - overdue_count: number of open cases past their deadline.
    """
    config = get_config(config_path)
    sar_cfg = config.get("reporting", {}).get("sar", {})
    reg = sar_cfg.get("regulation", regulation)

    now = datetime.now(UTC)
    metrics = TimelineMetrics()

    # Total / status counts
    all_cases = session.execute(select(Case)).scalars().all()
    metrics.total_cases = len(all_cases)
    metrics.closed_cases = sum(1 for c in all_cases if c.status == "CLOSED")
    metrics.open_cases = metrics.total_cases - metrics.closed_cases

    # Average investigation time (for closed cases with updated_at)
    closed_durations: list[float] = []
    for c in all_cases:
        if c.status == "CLOSED" and c.updated_at and c.created_at:
            created = c.created_at if c.created_at.tzinfo else c.created_at.replace(tzinfo=UTC)
            updated = c.updated_at if c.updated_at.tzinfo else c.updated_at.replace(tzinfo=UTC)
            delta = (updated - created).total_seconds() / 86400
            closed_durations.append(delta)
    if closed_durations:
        metrics.avg_investigation_days = sum(closed_durations) / len(closed_durations)

    # Average time to file (earliest alert → case closure)
    file_durations: list[float] = []
    for c in all_cases:
        if c.status == "CLOSED" and c.updated_at:
            stmt = (
                select(func.min(Alert.created_at))
                .join(CaseItem, CaseItem.alert_id == Alert.id)
                .where(CaseItem.case_id == c.id)
            )
            earliest = session.execute(stmt).scalar_one_or_none()
            if earliest:
                ea = earliest if earliest.tzinfo else earliest.replace(tzinfo=UTC)
                cu = c.updated_at if c.updated_at.tzinfo else c.updated_at.replace(tzinfo=UTC)
                delta = (cu - ea).total_seconds() / 86400
                file_durations.append(delta)
    if file_durations:
        metrics.avg_time_to_file_days = sum(file_durations) / len(file_durations)

    # Overdue count
    overdue = get_overdue_cases(session, regulation=reg, config_path=config_path)
    metrics.overdue_count = len(overdue)

    return metrics
