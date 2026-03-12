"""Management dashboard KPI computation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from aml_monitoring.models import Alert, Case, CaseItem


@dataclass
class DashboardKPIs:
    """KPI metrics for management dashboards."""

    # Alert volume
    total_alerts: int = 0
    alerts_by_severity: dict[str, int] = field(default_factory=dict)
    alerts_by_rule: dict[str, int] = field(default_factory=dict)

    # Conversion
    alert_to_sar_rate: float = 0.0

    # Investigation
    avg_investigation_days: float | None = None

    # False positive
    false_positive_rate: float = 0.0
    total_dispositioned: int = 0

    # Case backlog
    backlog_under_7d: int = 0
    backlog_7_14d: int = 0
    backlog_14_30d: int = 0
    backlog_over_30d: int = 0

    # Top rules
    top_triggered_rules: list[tuple[str, int]] = field(default_factory=list)

    # Trend (daily counts)
    alert_trend: list[dict[str, int | str]] = field(default_factory=list)

    # Period
    period_days: int = 30


def compute_kpis(session, period_days: int = 30) -> DashboardKPIs:
    """Compute dashboard KPIs for the given period.

    Args:
        session: SQLAlchemy session.
        period_days: Number of days to look back.

    Returns:
        DashboardKPIs dataclass.
    """
    kpis = DashboardKPIs(period_days=period_days)
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=period_days)

    # --- Alert metrics (within period) ---
    period_alerts = session.execute(
        select(Alert).where(Alert.created_at >= cutoff)
    ).scalars().all()

    kpis.total_alerts = len(period_alerts)

    # By severity
    sev_counts: dict[str, int] = defaultdict(int)
    for a in period_alerts:
        sev_counts[a.severity] += 1
    kpis.alerts_by_severity = dict(sev_counts)

    # By rule
    rule_counts: dict[str, int] = defaultdict(int)
    for a in period_alerts:
        rule_counts[a.rule_id] += 1
    kpis.alerts_by_rule = dict(rule_counts)

    # Top triggered rules (sorted descending)
    kpis.top_triggered_rules = sorted(rule_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # --- Alert-to-SAR conversion rate ---
    total_dispositioned = sum(1 for a in period_alerts if a.disposition is not None)
    sar_count = sum(1 for a in period_alerts if a.disposition == "sar")
    kpis.total_dispositioned = total_dispositioned
    kpis.alert_to_sar_rate = (sar_count / total_dispositioned) if total_dispositioned > 0 else 0.0

    # --- False positive rate ---
    fp_count = sum(1 for a in period_alerts if a.disposition == "false_positive")
    kpis.false_positive_rate = (fp_count / total_dispositioned) if total_dispositioned > 0 else 0.0

    # --- Average investigation time ---
    # Cases closed within period: created → updated_at (close time)
    closed_cases = session.execute(
        select(Case)
        .where(Case.status == "CLOSED")
        .where(Case.updated_at >= cutoff)
    ).scalars().all()

    inv_durations: list[float] = []
    for c in closed_cases:
        if c.created_at and c.updated_at:
            created = c.created_at if c.created_at.tzinfo else c.created_at.replace(tzinfo=UTC)
            updated = c.updated_at if c.updated_at.tzinfo else c.updated_at.replace(tzinfo=UTC)
            inv_durations.append((updated - created).total_seconds() / 86400)
    if inv_durations:
        kpis.avg_investigation_days = sum(inv_durations) / len(inv_durations)

    # --- Case backlog (open cases by age bucket) ---
    open_cases = session.execute(
        select(Case).where(Case.status != "CLOSED")
    ).scalars().all()

    for c in open_cases:
        if c.created_at:
            created = c.created_at if c.created_at.tzinfo else c.created_at.replace(tzinfo=UTC)
            age_days = (now - created).days
            if age_days < 7:
                kpis.backlog_under_7d += 1
            elif age_days < 14:
                kpis.backlog_7_14d += 1
            elif age_days < 30:
                kpis.backlog_14_30d += 1
            else:
                kpis.backlog_over_30d += 1

    # --- Alert trend (daily counts over period) ---
    trend: dict[str, int] = defaultdict(int)
    for a in period_alerts:
        if a.created_at:
            day_str = a.created_at.strftime("%Y-%m-%d")
            trend[day_str] += 1

    # Fill in zero-count days
    for i in range(period_days):
        day = (cutoff + timedelta(days=i)).strftime("%Y-%m-%d")
        if day not in trend:
            trend[day] = 0

    kpis.alert_trend = [
        {"date": d, "count": c}
        for d, c in sorted(trend.items())
    ]

    return kpis
