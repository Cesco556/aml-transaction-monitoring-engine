"""Reporting & Compliance module.

Re-exports the original generate_sar_report for backward compatibility,
plus new compliance-grade reporting functions.
"""

from __future__ import annotations

from aml_monitoring.reporting._legacy import generate_sar_report
from aml_monitoring.reporting.audit_export import export_audit_package
from aml_monitoring.reporting.kpis import DashboardKPIs, compute_kpis
from aml_monitoring.reporting.pdf_report import generate_pdf_report
from aml_monitoring.reporting.sar_fincen import SARReport, generate_fincen_sar
from aml_monitoring.reporting.timelines import (
    OverdueCase,
    TimelineMetrics,
    compute_filing_deadline,
    get_overdue_cases,
    get_timeline_metrics,
)

__all__ = [
    "generate_sar_report",
    "generate_fincen_sar",
    "SARReport",
    "generate_pdf_report",
    "compute_filing_deadline",
    "get_overdue_cases",
    "get_timeline_metrics",
    "OverdueCase",
    "TimelineMetrics",
    "compute_kpis",
    "DashboardKPIs",
    "export_audit_package",
]
