"""API router for Reporting & Compliance endpoints."""

from __future__ import annotations

import os
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from aml_monitoring.db import session_scope
from aml_monitoring.reporting.audit_export import export_audit_package
from aml_monitoring.reporting.kpis import compute_kpis
from aml_monitoring.reporting.pdf_report import generate_pdf_report
from aml_monitoring.reporting.sar_fincen import generate_fincen_sar
from aml_monitoring.reporting.timelines import get_overdue_cases, get_timeline_metrics

reports_router = APIRouter(prefix="/reports", tags=["reports"])


@reports_router.get("/kpis")
def get_kpis(period_days: int = Query(30, ge=1, le=365)):
    """Dashboard KPIs for the given period."""
    with session_scope() as session:
        kpis = compute_kpis(session, period_days=period_days)
    return asdict(kpis)


@reports_router.get("/overdue")
def get_overdue():
    """List overdue cases past their filing deadline."""
    with session_scope() as session:
        cases = get_overdue_cases(session)
    return [
        {
            "case_id": c.case_id,
            "case_status": c.case_status,
            "earliest_alert_at": c.earliest_alert_at.isoformat() if c.earliest_alert_at else None,
            "deadline": c.deadline.isoformat(),
            "days_overdue": c.days_overdue,
            "alert_count": c.alert_count,
        }
        for c in cases
    ]


@reports_router.get("/timeline-metrics")
def get_timeline_metrics_endpoint():
    """Filing timeline compliance statistics."""
    with session_scope() as session:
        metrics = get_timeline_metrics(session)
    return asdict(metrics)


@reports_router.post("/sar/{case_id}")
def generate_sar(case_id: int):
    """Generate a FinCEN SAR report for a case."""
    with session_scope() as session:
        try:
            report = generate_fincen_sar(case_id, session)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    return report.to_dict()


@reports_router.post("/pdf/{case_id}")
def generate_pdf(case_id: int):
    """Generate a PDF investigation report (file download)."""
    with session_scope() as session:
        try:
            tmp_dir = tempfile.mkdtemp(prefix="aml_pdf_")
            pdf_path = generate_pdf_report(
                case_id, session, output_path=os.path.join(tmp_dir, f"case_{case_id}.pdf")
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"case_{case_id}_report.pdf",
    )


@reports_router.post("/audit-export")
def generate_audit_export(
    date_from: str = Query(..., alias="from", description="Start date (YYYY-MM-DD)"),
    date_to: str = Query(..., alias="to", description="End date (YYYY-MM-DD)"),
):
    """Generate audit export ZIP for the given date range."""
    try:
        dt_from = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=UTC)
        dt_to = datetime.strptime(date_to, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=UTC
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD format")

    with session_scope() as session:
        tmp_dir = tempfile.mkdtemp(prefix="aml_audit_")
        zip_path = export_audit_package(session, dt_from, dt_to, output_dir=tmp_dir)

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=os.path.basename(zip_path),
    )
