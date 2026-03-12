"""FinCEN SAR report generation following BSA E-Filing structure."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from aml_monitoring.config import get_config
from aml_monitoring.models import Alert, Case, CaseItem, CaseNote, Customer, Account, Transaction


@dataclass
class FilerInfo:
    """BSA filer identification."""

    name: str = "AML Compliance Department"
    ein: str = "00-0000000"
    address: str = "123 Compliance St"


@dataclass
class SubjectInfo:
    """SAR subject (the person/entity under investigation)."""

    name: str = ""
    account_numbers: list[str] = field(default_factory=list)
    country: str = ""
    customer_id: int | None = None


@dataclass
class SuspiciousActivity:
    """Suspicious activity details for SAR filing."""

    description: str = ""
    total_amount: float = 0.0
    date_range_start: datetime | None = None
    date_range_end: datetime | None = None
    instruments: list[str] = field(default_factory=list)
    activity_types: list[str] = field(default_factory=list)


@dataclass
class SARReport:
    """Complete FinCEN SAR report structure (BSA E-Filing format)."""

    report_id: str = ""
    filing_type: str = "INITIAL"  # INITIAL, CORRECT, CONTINUING
    filer: FilerInfo = field(default_factory=FilerInfo)
    subject: SubjectInfo = field(default_factory=SubjectInfo)
    suspicious_activity: SuspiciousActivity = field(default_factory=SuspiciousActivity)
    narrative: str = ""
    case_id: int | None = None
    alert_ids: list[int] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Export to dictionary (JSON-serialisable)."""
        d = asdict(self)
        # Convert datetimes to ISO strings
        d["generated_at"] = self.generated_at.isoformat()
        sa = d["suspicious_activity"]
        if sa["date_range_start"]:
            sa["date_range_start"] = self.suspicious_activity.date_range_start.isoformat()
        if sa["date_range_end"]:
            sa["date_range_end"] = self.suspicious_activity.date_range_end.isoformat()
        return d

    def to_json(self, indent: int = 2) -> str:
        """Export to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_xml(self) -> str:
        """Export to XML following FinCEN BSA E-Filing structure."""
        root = ET.Element("BSAReport")
        root.set("xmlns", "https://www.fincen.gov/bsa")

        # Filing info
        filing = ET.SubElement(root, "FilingInfo")
        ET.SubElement(filing, "ReportID").text = self.report_id
        ET.SubElement(filing, "FilingType").text = self.filing_type
        ET.SubElement(filing, "GeneratedAt").text = self.generated_at.isoformat()

        # Filer
        filer_el = ET.SubElement(root, "Filer")
        ET.SubElement(filer_el, "Name").text = self.filer.name
        ET.SubElement(filer_el, "EIN").text = self.filer.ein
        ET.SubElement(filer_el, "Address").text = self.filer.address

        # Subject
        subject_el = ET.SubElement(root, "Subject")
        ET.SubElement(subject_el, "Name").text = self.subject.name
        ET.SubElement(subject_el, "Country").text = self.subject.country
        accounts_el = ET.SubElement(subject_el, "AccountNumbers")
        for acct in self.subject.account_numbers:
            ET.SubElement(accounts_el, "Account").text = acct

        # Suspicious Activity
        activity_el = ET.SubElement(root, "SuspiciousActivity")
        ET.SubElement(activity_el, "Description").text = self.suspicious_activity.description
        ET.SubElement(activity_el, "TotalAmount").text = f"{self.suspicious_activity.total_amount:.2f}"
        if self.suspicious_activity.date_range_start:
            ET.SubElement(activity_el, "DateRangeStart").text = (
                self.suspicious_activity.date_range_start.isoformat()
            )
        if self.suspicious_activity.date_range_end:
            ET.SubElement(activity_el, "DateRangeEnd").text = (
                self.suspicious_activity.date_range_end.isoformat()
            )
        instruments_el = ET.SubElement(activity_el, "Instruments")
        for inst in self.suspicious_activity.instruments:
            ET.SubElement(instruments_el, "Instrument").text = inst
        types_el = ET.SubElement(activity_el, "ActivityTypes")
        for at in self.suspicious_activity.activity_types:
            ET.SubElement(types_el, "Type").text = at

        # Narrative
        ET.SubElement(root, "Narrative").text = self.narrative

        # Case/Alert references
        refs = ET.SubElement(root, "References")
        if self.case_id is not None:
            ET.SubElement(refs, "CaseID").text = str(self.case_id)
        for aid in self.alert_ids:
            ET.SubElement(refs, "AlertID").text = str(aid)

        return ET.tostring(root, encoding="unicode", xml_declaration=True)


def generate_fincen_sar(
    case_id: int,
    session,
    config_path: str | None = None,
) -> SARReport:
    """Build a FinCEN SAR from a case and its linked alerts/transactions.

    Args:
        case_id: The case to generate the SAR for.
        session: SQLAlchemy session.
        config_path: Optional config file path.

    Returns:
        Populated SARReport dataclass.
    """
    config = get_config(config_path)
    reporting_cfg = config.get("reporting", {})
    sar_cfg = reporting_cfg.get("sar", {})
    filer_cfg = sar_cfg.get("filer", {})

    # Load case
    case = session.execute(select(Case).where(Case.id == case_id)).scalar_one_or_none()
    if case is None:
        raise ValueError(f"Case {case_id} not found")

    # Load case items (linked alerts and transactions)
    items = session.execute(
        select(CaseItem).where(CaseItem.case_id == case_id)
    ).scalars().all()

    alert_ids = [i.alert_id for i in items if i.alert_id is not None]
    transaction_ids = [i.transaction_id for i in items if i.transaction_id is not None]

    # Load alerts
    alerts: list[Alert] = []
    if alert_ids:
        alerts = session.execute(
            select(Alert).where(Alert.id.in_(alert_ids))
        ).scalars().all()
        # Also gather transaction IDs from alerts
        for a in alerts:
            if a.transaction_id not in transaction_ids:
                transaction_ids.append(a.transaction_id)

    # Load transactions
    transactions: list[Transaction] = []
    if transaction_ids:
        transactions = session.execute(
            select(Transaction).where(Transaction.id.in_(transaction_ids))
        ).scalars().all()

    # Determine subject from transactions → accounts → customers
    subject = SubjectInfo()
    account_ids = list({t.account_id for t in transactions})
    if account_ids:
        accounts = session.execute(
            select(Account).where(Account.id.in_(account_ids))
        ).scalars().all()
        subject.account_numbers = [a.iban_or_acct for a in accounts]

        customer_ids = list({a.customer_id for a in accounts})
        if customer_ids:
            customer = session.execute(
                select(Customer).where(Customer.id == customer_ids[0])
            ).scalar_one_or_none()
            if customer:
                subject.name = customer.name
                subject.country = customer.country
                subject.customer_id = customer.id

    # Build suspicious activity summary
    total_amount = sum(t.amount for t in transactions)
    timestamps = [t.ts for t in transactions if t.ts]
    date_start = min(timestamps) if timestamps else None
    date_end = max(timestamps) if timestamps else None

    # Collect unique channels/instruments
    instruments = list({t.channel for t in transactions if t.channel})
    activity_types = list({a.rule_id for a in alerts})

    # Build narrative from alerts and case notes
    narrative_parts = []
    narrative_parts.append(
        f"Suspicious Activity Report for Case #{case_id}. "
        f"Status: {case.status}. Priority: {case.priority}."
    )
    if alerts:
        narrative_parts.append(
            f"\n{len(alerts)} alert(s) triggered across {len(transactions)} transaction(s) "
            f"totalling {total_amount:,.2f}."
        )
        for a in alerts:
            narrative_parts.append(f"\n- Alert #{a.id} [{a.severity}]: {a.reason}")

    # Case notes
    notes = session.execute(
        select(CaseNote).where(CaseNote.case_id == case_id).order_by(CaseNote.created_at)
    ).scalars().all()
    if notes:
        narrative_parts.append("\n\nInvestigation Notes:")
        for n in notes:
            narrative_parts.append(f"\n[{n.created_at}] {n.actor}: {n.note}")

    report = SARReport(
        report_id=f"SAR-{case_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        filing_type="INITIAL",
        filer=FilerInfo(
            name=filer_cfg.get("name", "AML Compliance Department"),
            ein=filer_cfg.get("ein", "00-0000000"),
            address=filer_cfg.get("address", "123 Compliance St"),
        ),
        subject=subject,
        suspicious_activity=SuspiciousActivity(
            description=f"Suspicious activity detected via {len(activity_types)} rule(s)",
            total_amount=total_amount,
            date_range_start=date_start,
            date_range_end=date_end,
            instruments=instruments,
            activity_types=activity_types,
        ),
        narrative="".join(narrative_parts),
        case_id=case_id,
        alert_ids=[a.id for a in alerts],
    )

    return report
