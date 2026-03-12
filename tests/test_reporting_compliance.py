"""Tests for Phase 8: Reporting & Compliance."""

from __future__ import annotations

import json
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from aml_monitoring.models import (
    Account,
    Alert,
    AuditLog,
    Base,
    Case,
    CaseItem,
    CaseNote,
    Customer,
    Transaction,
)


def _test_config_path():
    """Create a temporary config file with valid countries for tests."""
    import tempfile as _tf

    content = {
        "rules": {
            "high_risk_country": {
                "enabled": True,
                "countries": ["IR", "KP"],
                "severity": "high",
                "score_delta": 25.0,
                "list_version": "1.0",
                "effective_date": "2026-01-01",
            }
        },
        "reporting": {
            "output_dir": "./reports",
            "sar": {
                "regulation": "fincen",
                "filing_deadline_days": 30,
                "extended_deadline_days": 60,
                "filer": {
                    "name": "AML Compliance Department",
                    "ein": "00-0000000",
                    "address": "123 Compliance St",
                },
            },
            "pdf": {"output_dir": "./reports/pdf", "logo_path": None},
            "audit": {"output_dir": "./reports/audit"},
        },
    }
    fd, path = _tf.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        yaml.dump(content, f)
    return path


@pytest.fixture(scope="module")
def test_config():
    """Module-scoped test config path."""
    path = _test_config_path()
    yield path
    os.unlink(path)


@pytest.fixture()
def db_session():
    """In-memory SQLite session with schema."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def populated_session(db_session):
    """Session with sample data: customer, account, transactions, alerts, case."""
    s = db_session
    now = datetime.now(UTC)

    # Customer + Account
    customer = Customer(name="John Doe", country="US", base_risk=15.0)
    s.add(customer)
    s.flush()

    account = Account(customer_id=customer.id, iban_or_acct="US12345678")
    s.add(account)
    s.flush()

    # Transactions
    txns = []
    for i in range(5):
        t = Transaction(
            account_id=account.id,
            ts=now - timedelta(days=10 - i),
            amount=5000.0 + i * 1000,
            currency="USD",
            merchant=f"Merchant_{i}",
            counterparty=f"CP_{i}",
            country="US" if i < 3 else "IR",
            channel="wire" if i % 2 == 0 else "online",
            direction="out",
        )
        s.add(t)
        txns.append(t)
    s.flush()

    # Alerts
    alerts = []
    for i, t in enumerate(txns[:3]):
        severity = "high" if i == 0 else "medium"
        disposition = None
        if i == 0:
            disposition = "sar"
        elif i == 1:
            disposition = "false_positive"
        a = Alert(
            transaction_id=t.id,
            rule_id="high_value" if i < 2 else "geo_mismatch",
            severity=severity,
            score=75.0 - i * 10,
            reason=f"Test alert reason {i}",
            status="closed" if disposition else "open",
            disposition=disposition,
            created_at=now - timedelta(days=10 - i),
        )
        s.add(a)
        alerts.append(a)
    s.flush()

    # Case
    case = Case(
        status="INVESTIGATING",
        priority="HIGH",
        assigned_to="analyst@compliance.com",
        created_at=now - timedelta(days=9),
    )
    s.add(case)
    s.flush()

    # Link alerts and a transaction to the case
    for a in alerts:
        s.add(CaseItem(case_id=case.id, alert_id=a.id))
    s.add(CaseItem(case_id=case.id, transaction_id=txns[3].id))
    s.flush()

    # Case note
    s.add(
        CaseNote(
            case_id=case.id,
            note="Initial review completed. Suspicious pattern detected.",
            actor="analyst@compliance.com",
            correlation_id="test-corr-1",
        )
    )
    s.flush()

    # Audit log
    s.add(
        AuditLog(
            correlation_id="test-corr-1",
            action="case_create",
            entity_type="case",
            entity_id=str(case.id),
            actor="system",
            ts=now - timedelta(days=9),
            details_json={"priority": "HIGH"},
        )
    )
    s.flush()
    s.commit()

    return s


# ============================================================
# 1. FinCEN SAR Generation
# ============================================================


class TestFinCENSAR:
    def test_generate_sar_basic(self, populated_session, test_config):
        from aml_monitoring.reporting.sar_fincen import generate_fincen_sar

        report = generate_fincen_sar(case_id=1, session=populated_session, config_path=test_config)
        assert report.case_id == 1
        assert report.filing_type == "INITIAL"
        assert report.filer.name == "AML Compliance Department"
        assert report.subject.name == "John Doe"
        assert len(report.alert_ids) == 3
        assert report.suspicious_activity.total_amount > 0
        assert "SAR-1-" in report.report_id

    def test_sar_required_fields(self, populated_session, test_config):
        from aml_monitoring.reporting.sar_fincen import generate_fincen_sar

        report = generate_fincen_sar(case_id=1, session=populated_session, config_path=test_config)
        assert report.filer.ein != ""
        assert report.filer.address != ""
        assert report.narrative != ""
        assert report.suspicious_activity.description != ""

    def test_sar_to_json(self, populated_session, test_config):
        from aml_monitoring.reporting.sar_fincen import generate_fincen_sar

        report = generate_fincen_sar(case_id=1, session=populated_session, config_path=test_config)
        j = report.to_json()
        data = json.loads(j)
        assert data["case_id"] == 1
        assert "filer" in data
        assert "subject" in data
        assert "suspicious_activity" in data

    def test_sar_to_xml(self, populated_session, test_config):
        from aml_monitoring.reporting.sar_fincen import generate_fincen_sar

        report = generate_fincen_sar(case_id=1, session=populated_session, config_path=test_config)
        xml_str = report.to_xml()
        # Parse XML - validates well-formedness
        ns = {"bsa": "https://www.fincen.gov/bsa"}
        root = ET.fromstring(xml_str)
        assert "BSAReport" in root.tag
        assert root.find("bsa:Filer", ns) is not None
        assert root.find("bsa:Subject", ns) is not None
        assert root.find("bsa:SuspiciousActivity", ns) is not None
        assert root.find("bsa:Narrative", ns) is not None
        assert root.find("bsa:Narrative", ns).text != ""

    def test_sar_not_found(self, db_session, test_config):
        from aml_monitoring.reporting.sar_fincen import generate_fincen_sar

        with pytest.raises(ValueError, match="Case 999 not found"):
            generate_fincen_sar(case_id=999, session=db_session, config_path=test_config)

    def test_sar_to_dict(self, populated_session, test_config):
        from aml_monitoring.reporting.sar_fincen import generate_fincen_sar

        report = generate_fincen_sar(case_id=1, session=populated_session, config_path=test_config)
        d = report.to_dict()
        assert isinstance(d, dict)
        assert d["filing_type"] == "INITIAL"


# ============================================================
# 2. PDF Report Generation
# ============================================================


class TestPDFReport:
    def test_generate_pdf(self, populated_session, test_config):
        from aml_monitoring.reporting.pdf_report import generate_pdf_report

        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_pdf_report(
                case_id=1,
                session=populated_session,
                output_path=os.path.join(tmpdir, "test_report.pdf"),
                config_path=test_config,
            )
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
            assert path.endswith(".pdf")

    def test_pdf_not_found(self, db_session, test_config):
        from aml_monitoring.reporting.pdf_report import generate_pdf_report

        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="Case 999 not found"):
                generate_pdf_report(
                    case_id=999,
                    session=db_session,
                    output_path=os.path.join(tmpdir, "test.pdf"),
                    config_path=test_config,
                )

    def test_pdf_creates_parent_dirs(self, populated_session, test_config):
        from aml_monitoring.reporting.pdf_report import generate_pdf_report

        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_pdf_report(
                case_id=1,
                session=populated_session,
                output_path=os.path.join(tmpdir, "sub", "dir", "report.pdf"),
                config_path=test_config,
            )
            assert os.path.exists(path)


# ============================================================
# 3. Regulatory Timelines
# ============================================================


class TestTimelines:
    def test_compute_deadline_fincen(self):
        from aml_monitoring.reporting.timelines import compute_filing_deadline

        base = datetime(2026, 1, 1, tzinfo=UTC)
        deadline = compute_filing_deadline(base, regulation="fincen")
        assert deadline == base + timedelta(days=30)

    def test_compute_deadline_extended(self):
        from aml_monitoring.reporting.timelines import compute_filing_deadline

        base = datetime(2026, 1, 1, tzinfo=UTC)
        deadline = compute_filing_deadline(base, regulation="fincen", extended=True)
        assert deadline == base + timedelta(days=60)

    def test_compute_deadline_fca(self):
        from aml_monitoring.reporting.timelines import compute_filing_deadline

        base = datetime(2026, 1, 1, tzinfo=UTC)
        deadline = compute_filing_deadline(base, regulation="fca")
        assert deadline == base + timedelta(days=15)

    def test_compute_deadline_amld(self):
        from aml_monitoring.reporting.timelines import compute_filing_deadline

        base = datetime(2026, 1, 1, tzinfo=UTC)
        deadline = compute_filing_deadline(base, regulation="amld")
        assert deadline == base + timedelta(days=30)

    def test_compute_deadline_unknown(self):
        from aml_monitoring.reporting.timelines import compute_filing_deadline

        with pytest.raises(ValueError, match="Unknown regulation"):
            compute_filing_deadline(datetime.now(UTC), regulation="unknown")

    def test_get_overdue_cases(self, populated_session, test_config):
        """The populated session has alerts from ~10 days ago with a non-closed case.
        With FinCEN's 30-day deadline, they shouldn't be overdue yet unless we manipulate dates."""
        from aml_monitoring.reporting.timelines import get_overdue_cases

        # Current alerts are ~10 days old, deadline is 30 days — not overdue
        overdue = get_overdue_cases(populated_session, config_path=test_config)
        assert isinstance(overdue, list)
        # Not overdue with current data (10 days < 30 day deadline)
        assert len(overdue) == 0

    def test_get_overdue_cases_with_old_alerts(self, db_session, test_config):
        """Create a case with alerts old enough to be overdue."""
        from aml_monitoring.reporting.timelines import get_overdue_cases

        s = db_session
        now = datetime.now(UTC)

        customer = Customer(name="Old Case", country="US", base_risk=10.0)
        s.add(customer)
        s.flush()

        account = Account(customer_id=customer.id, iban_or_acct="OLDACCT001")
        s.add(account)
        s.flush()

        txn = Transaction(
            account_id=account.id, ts=now - timedelta(days=60), amount=50000, currency="USD"
        )
        s.add(txn)
        s.flush()

        alert = Alert(
            transaction_id=txn.id,
            rule_id="high_value",
            severity="high",
            score=90,
            reason="Old alert",
            status="open",
            created_at=now - timedelta(days=45),  # 45 days ago > 30 day deadline
        )
        s.add(alert)
        s.flush()

        case = Case(status="INVESTIGATING", priority="HIGH", created_at=now - timedelta(days=44))
        s.add(case)
        s.flush()

        s.add(CaseItem(case_id=case.id, alert_id=alert.id))
        s.flush()
        s.commit()

        overdue = get_overdue_cases(s, config_path=test_config)
        assert len(overdue) == 1
        assert overdue[0].case_id == case.id
        assert overdue[0].days_overdue >= 14  # 45 - 30 = 15 days overdue

    def test_timeline_metrics(self, populated_session, test_config):
        from aml_monitoring.reporting.timelines import get_timeline_metrics

        metrics = get_timeline_metrics(populated_session, config_path=test_config)
        assert metrics.total_cases >= 1
        assert metrics.open_cases >= 1
        assert isinstance(metrics.overdue_count, int)


# ============================================================
# 4. KPI Computation
# ============================================================


class TestKPIs:
    def test_compute_kpis_basic(self, populated_session):
        from aml_monitoring.reporting.kpis import compute_kpis

        kpis = compute_kpis(populated_session, period_days=30)
        assert kpis.total_alerts == 3
        assert kpis.period_days == 30

    def test_kpi_severity_breakdown(self, populated_session):
        from aml_monitoring.reporting.kpis import compute_kpis

        kpis = compute_kpis(populated_session, period_days=30)
        assert "high" in kpis.alerts_by_severity
        assert "medium" in kpis.alerts_by_severity

    def test_kpi_rule_breakdown(self, populated_session):
        from aml_monitoring.reporting.kpis import compute_kpis

        kpis = compute_kpis(populated_session, period_days=30)
        assert "high_value" in kpis.alerts_by_rule
        assert "geo_mismatch" in kpis.alerts_by_rule

    def test_kpi_conversion_rate(self, populated_session):
        from aml_monitoring.reporting.kpis import compute_kpis

        kpis = compute_kpis(populated_session, period_days=30)
        # 1 sar out of 2 dispositioned
        assert kpis.alert_to_sar_rate == pytest.approx(0.5)
        assert kpis.total_dispositioned == 2

    def test_kpi_false_positive_rate(self, populated_session):
        from aml_monitoring.reporting.kpis import compute_kpis

        kpis = compute_kpis(populated_session, period_days=30)
        # 1 false_positive out of 2 dispositioned
        assert kpis.false_positive_rate == pytest.approx(0.5)

    def test_kpi_alert_trend(self, populated_session):
        from aml_monitoring.reporting.kpis import compute_kpis

        kpis = compute_kpis(populated_session, period_days=30)
        assert len(kpis.alert_trend) >= 1
        # Each entry has date and count
        for entry in kpis.alert_trend:
            assert "date" in entry
            assert "count" in entry

    def test_kpi_empty_db(self, db_session):
        from aml_monitoring.reporting.kpis import compute_kpis

        kpis = compute_kpis(db_session, period_days=30)
        assert kpis.total_alerts == 0
        assert kpis.alert_to_sar_rate == 0.0
        assert kpis.false_positive_rate == 0.0

    def test_kpi_top_rules(self, populated_session):
        from aml_monitoring.reporting.kpis import compute_kpis

        kpis = compute_kpis(populated_session, period_days=30)
        assert len(kpis.top_triggered_rules) > 0
        # First rule should have highest count
        rule_name, count = kpis.top_triggered_rules[0]
        assert count >= 1


# ============================================================
# 5. Audit Export
# ============================================================


class TestAuditExport:
    def test_export_creates_zip(self, populated_session, test_config):
        from aml_monitoring.reporting.audit_export import export_audit_package

        with tempfile.TemporaryDirectory() as tmpdir:
            now = datetime.now(UTC)
            zip_path = export_audit_package(
                populated_session,
                date_from=now - timedelta(days=30),
                date_to=now + timedelta(days=1),
                output_dir=tmpdir,
                config_path=test_config,
            )
            assert os.path.exists(zip_path)
            assert zip_path.endswith(".zip")
            assert os.path.getsize(zip_path) > 0

    def test_export_contains_expected_files(self, populated_session, test_config):
        from aml_monitoring.reporting.audit_export import export_audit_package

        with tempfile.TemporaryDirectory() as tmpdir:
            now = datetime.now(UTC)
            zip_path = export_audit_package(
                populated_session,
                date_from=now - timedelta(days=30),
                date_to=now + timedelta(days=1),
                output_dir=tmpdir,
                config_path=test_config,
            )
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                assert "alerts.json" in names
                assert "cases.json" in names
                assert "summary.json" in names
                assert "audit_logs.json" in names

    def test_export_summary_stats(self, populated_session, test_config):
        from aml_monitoring.reporting.audit_export import export_audit_package

        with tempfile.TemporaryDirectory() as tmpdir:
            now = datetime.now(UTC)
            zip_path = export_audit_package(
                populated_session,
                date_from=now - timedelta(days=30),
                date_to=now + timedelta(days=1),
                output_dir=tmpdir,
                config_path=test_config,
            )
            with zipfile.ZipFile(zip_path, "r") as zf:
                summary = json.loads(zf.read("summary.json"))
                assert summary["total_alerts"] == 3
                assert summary["total_cases"] >= 1
                assert "audit_chain_verification" in summary

    def test_export_empty_range(self, populated_session, test_config):
        from aml_monitoring.reporting.audit_export import export_audit_package

        with tempfile.TemporaryDirectory() as tmpdir:
            # Far future range — no data
            zip_path = export_audit_package(
                populated_session,
                date_from=datetime(2099, 1, 1, tzinfo=UTC),
                date_to=datetime(2099, 12, 31, tzinfo=UTC),
                output_dir=tmpdir,
                config_path=test_config,
            )
            with zipfile.ZipFile(zip_path, "r") as zf:
                summary = json.loads(zf.read("summary.json"))
                assert summary["total_alerts"] == 0

    def test_export_csv_files(self, populated_session, test_config):
        from aml_monitoring.reporting.audit_export import export_audit_package

        with tempfile.TemporaryDirectory() as tmpdir:
            now = datetime.now(UTC)
            zip_path = export_audit_package(
                populated_session,
                date_from=now - timedelta(days=30),
                date_to=now + timedelta(days=1),
                output_dir=tmpdir,
                config_path=test_config,
            )
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                assert "alerts.csv" in names


# ============================================================
# 6. API Endpoints
# ============================================================


class TestReportsAPI:
    """Test API endpoints using a file-based SQLite DB for thread safety."""

    @pytest.fixture(autouse=True)
    def setup_app(self, test_config, tmp_path):
        """Setup test client with file-based SQLite DB and valid config."""
        from fastapi.testclient import TestClient

        from aml_monitoring.config import get_config
        from aml_monitoring.db import init_db, session_scope

        db_path = tmp_path / "test_api.db"
        db_url = f"sqlite:///{db_path}"

        # Load the valid test config and patch get_config globally
        valid_cfg = get_config(test_config)
        valid_cfg.setdefault("database", {})["url"] = db_url
        valid_cfg.setdefault("database", {})["echo"] = False
        valid_cfg.setdefault("security", {})["rate_limiting"] = {"enabled": False}

        init_db(db_url)

        # Populate the DB
        now = datetime.now(UTC)
        with session_scope() as s:
            customer = Customer(name="API Test", country="US", base_risk=10.0)
            s.add(customer)
            s.flush()
            account = Account(customer_id=customer.id, iban_or_acct="APITEST001")
            s.add(account)
            s.flush()
            txn = Transaction(
                account_id=account.id, ts=now - timedelta(days=5),
                amount=15000, currency="USD", channel="wire",
            )
            s.add(txn)
            s.flush()
            alert = Alert(
                transaction_id=txn.id, rule_id="high_value", severity="high",
                score=80, reason="API test alert", status="open",
                created_at=now - timedelta(days=5),
            )
            s.add(alert)
            s.flush()
            case = Case(
                status="INVESTIGATING", priority="HIGH",
                created_at=now - timedelta(days=4),
            )
            s.add(case)
            s.flush()
            s.add(CaseItem(case_id=case.id, alert_id=alert.id))
            s.flush()

        # Patch get_config everywhere it's imported
        patchers = [
            patch("aml_monitoring.config.get_config", return_value=valid_cfg),
            patch("aml_monitoring.reporting.timelines.get_config", return_value=valid_cfg),
            patch("aml_monitoring.reporting.sar_fincen.get_config", return_value=valid_cfg),
            patch("aml_monitoring.reporting.pdf_report.get_config", return_value=valid_cfg),
            patch("aml_monitoring.reporting.audit_export.get_config", return_value=valid_cfg),
        ]
        for p in patchers:
            p.start()

        from aml_monitoring.api import app

        self.client = TestClient(app)
        yield
        for p in patchers:
            p.stop()

    def test_kpis_endpoint(self):
        resp = self.client.get("/reports/kpis?period_days=30")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_alerts" in data
        assert "alert_to_sar_rate" in data

    def test_overdue_endpoint(self):
        resp = self.client.get("/reports/overdue")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_timeline_metrics_endpoint(self):
        resp = self.client.get("/reports/timeline-metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_cases" in data
        assert "overdue_count" in data

    def test_sar_endpoint(self):
        resp = self.client.post("/reports/sar/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["case_id"] == 1
        assert "filer" in data

    def test_sar_not_found(self):
        resp = self.client.post("/reports/sar/999")
        assert resp.status_code == 404

    def test_pdf_endpoint(self):
        resp = self.client.post("/reports/pdf/1")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert len(resp.content) > 0

    def test_pdf_not_found(self):
        resp = self.client.post("/reports/pdf/999")
        assert resp.status_code == 404


# ============================================================
# 7. Integration: SAR → XML round-trip
# ============================================================


class TestSARXMLIntegrity:
    def test_xml_has_all_required_elements(self, populated_session, test_config):
        from aml_monitoring.reporting.sar_fincen import generate_fincen_sar

        report = generate_fincen_sar(case_id=1, session=populated_session, config_path=test_config)
        xml_str = report.to_xml()
        ns = {"bsa": "https://www.fincen.gov/bsa"}
        root = ET.fromstring(xml_str)

        # Required BSA fields
        assert root.find("bsa:FilingInfo/bsa:ReportID", ns).text.startswith("SAR-1-")
        assert root.find("bsa:FilingInfo/bsa:FilingType", ns).text == "INITIAL"
        assert root.find("bsa:Filer/bsa:Name", ns).text == "AML Compliance Department"
        assert root.find("bsa:Filer/bsa:EIN", ns).text == "00-0000000"
        assert root.find("bsa:Subject/bsa:Name", ns).text == "John Doe"
        assert root.find("bsa:SuspiciousActivity/bsa:TotalAmount", ns) is not None
        assert float(root.find("bsa:SuspiciousActivity/bsa:TotalAmount", ns).text) > 0
