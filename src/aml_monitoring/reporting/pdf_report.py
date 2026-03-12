"""Professional PDF investigation report generation using fpdf2."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fpdf import FPDF
from sqlalchemy import select

from aml_monitoring.config import get_config
from aml_monitoring.models import Alert, Case, CaseItem, CaseNote, Customer, Account, Transaction


class _ReportPDF(FPDF):
    """Custom PDF with headers and footers."""

    def __init__(self, case_id: int, logo_path: str | None = None):
        super().__init__()
        self.case_id = case_id
        self.logo_path = logo_path

    def header(self):
        if self.logo_path and Path(self.logo_path).exists():
            self.image(self.logo_path, 10, 8, 30)
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 10, "AML Investigation Report", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 9)
        self.cell(
            0, 5,
            f"Case #{self.case_id} | Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
            align="C", new_x="LMARGIN", new_y="NEXT",
        )
        self.line(10, self.get_y() + 2, 200, self.get_y() + 2)
        self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}} | CONFIDENTIAL", align="C")

    def section_title(self, title: str):
        self.set_font("Helvetica", "B", 12)
        self.set_fill_color(230, 235, 240)
        self.cell(0, 8, f"  {title}", fill=True, new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

    def body_text(self, text: str):
        self.set_font("Helvetica", "", 10)
        # Replace unicode chars that Helvetica can't render
        safe = text.replace("\u2014", "--").replace("\u2013", "-").replace("\u2019", "'").replace("\u2018", "'")
        self.multi_cell(0, 5, safe)
        self.ln(2)

    def key_value(self, key: str, value: str):
        self.set_font("Helvetica", "B", 10)
        self.cell(50, 6, f"{key}:", new_x="END")
        self.set_font("Helvetica", "", 10)
        self.cell(0, 6, value, new_x="LMARGIN", new_y="NEXT")


def generate_pdf_report(
    case_id: int,
    session,
    output_path: str | Path,
    config_path: str | None = None,
) -> str:
    """Generate a professional PDF investigation report for a case.

    Args:
        case_id: Case ID.
        session: SQLAlchemy session.
        output_path: Where to write the PDF file.
        config_path: Optional config path.

    Returns:
        Absolute path to the generated PDF.
    """
    config = get_config(config_path)
    pdf_cfg = config.get("reporting", {}).get("pdf", {})
    logo_path = pdf_cfg.get("logo_path")

    # Load case
    case = session.execute(select(Case).where(Case.id == case_id)).scalar_one_or_none()
    if case is None:
        raise ValueError(f"Case {case_id} not found")

    # Load items, alerts, transactions
    items = session.execute(
        select(CaseItem).where(CaseItem.case_id == case_id)
    ).scalars().all()

    alert_ids = [i.alert_id for i in items if i.alert_id is not None]
    transaction_ids = [i.transaction_id for i in items if i.transaction_id is not None]

    alerts: list[Alert] = []
    if alert_ids:
        alerts = session.execute(
            select(Alert).where(Alert.id.in_(alert_ids))
        ).scalars().all()
        for a in alerts:
            if a.transaction_id not in transaction_ids:
                transaction_ids.append(a.transaction_id)

    transactions: list[Transaction] = []
    if transaction_ids:
        transactions = session.execute(
            select(Transaction).where(Transaction.id.in_(transaction_ids))
        ).scalars().all()

    # Load subject info
    account_ids = list({t.account_id for t in transactions})
    accounts: list[Account] = []
    customer: Customer | None = None
    if account_ids:
        accounts = session.execute(
            select(Account).where(Account.id.in_(account_ids))
        ).scalars().all()
        if accounts:
            customer = session.execute(
                select(Customer).where(Customer.id == accounts[0].customer_id)
            ).scalar_one_or_none()

    # Case notes
    notes = session.execute(
        select(CaseNote).where(CaseNote.case_id == case_id).order_by(CaseNote.created_at)
    ).scalars().all()

    # Build PDF
    pdf = _ReportPDF(case_id=case_id, logo_path=logo_path)
    pdf.alias_nb_pages()
    pdf.add_page()

    # 1. Executive Summary
    pdf.section_title("1. Executive Summary")
    total_amount = sum(t.amount for t in transactions)
    pdf.body_text(
        f"This report covers Case #{case_id} (Status: {case.status}, Priority: {case.priority}). "
        f"The investigation involves {len(alerts)} alert(s) across {len(transactions)} transaction(s) "
        f"totalling {total_amount:,.2f}. "
        f"{'Assigned to: ' + case.assigned_to if case.assigned_to else 'Unassigned.'}"
    )

    # 2. Subject Details
    pdf.section_title("2. Subject Details")
    if customer:
        pdf.key_value("Customer Name", customer.name)
        pdf.key_value("Country", customer.country)
        pdf.key_value("Customer ID", str(customer.id))
        pdf.key_value("Base Risk", str(customer.base_risk))
    else:
        pdf.body_text("No customer information linked to this case.")
    if accounts:
        pdf.key_value("Account(s)", ", ".join(a.iban_or_acct for a in accounts))
    pdf.ln(2)

    # 3. Transaction Timeline
    pdf.section_title("3. Transaction Timeline")
    sorted_txns = sorted(transactions, key=lambda t: t.ts if t.ts else datetime.min)
    if sorted_txns:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(20, 6, "ID", border=1)
        pdf.cell(40, 6, "Date/Time", border=1)
        pdf.cell(30, 6, "Amount", border=1)
        pdf.cell(20, 6, "Curr", border=1)
        pdf.cell(40, 6, "Counterparty", border=1)
        pdf.cell(20, 6, "Country", border=1)
        pdf.cell(20, 6, "Channel", border=1, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8)
        for t in sorted_txns[:50]:  # Cap at 50 for readability
            pdf.cell(20, 5, str(t.id), border=1)
            pdf.cell(40, 5, t.ts.strftime("%Y-%m-%d %H:%M") if t.ts else "N/A", border=1)
            pdf.cell(30, 5, f"{t.amount:,.2f}", border=1)
            pdf.cell(20, 5, t.currency or "USD", border=1)
            pdf.cell(40, 5, (t.counterparty or "N/A")[:20], border=1)
            pdf.cell(20, 5, t.country or "N/A", border=1)
            pdf.cell(20, 5, (t.channel or "N/A")[:10], border=1, new_x="LMARGIN", new_y="NEXT")
        if len(transactions) > 50:
            pdf.body_text(f"... and {len(transactions) - 50} more transactions.")
    else:
        pdf.body_text("No transactions linked to this case.")
    pdf.ln(2)

    # 4. Alert History
    pdf.section_title("4. Alert History")
    for a in alerts:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, f"Alert #{a.id} - {a.rule_id} [{a.severity}]", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, f"Score: {a.score} | Status: {a.status} | Disposition: {a.disposition or 'N/A'}", new_x="LMARGIN", new_y="NEXT")
        pdf.body_text(f"Reason: {a.reason}")
    if not alerts:
        pdf.body_text("No alerts linked to this case.")

    # 5. Network Diagram Placeholder
    pdf.section_title("5. Network Analysis")
    pdf.body_text(
        "[Network diagram placeholder - integrate with network export module for visualization. "
        "See 'aml network-export d3' for graph data.]"
    )

    # 6. Risk Assessment
    pdf.section_title("6. Risk Assessment")
    severity_counts: dict[str, int] = {}
    for a in alerts:
        severity_counts[a.severity] = severity_counts.get(a.severity, 0) + 1
    if severity_counts:
        pdf.body_text("Alert severity distribution:")
        for sev, count in sorted(severity_counts.items()):
            pdf.body_text(f"  - {sev}: {count}")
    avg_score = sum(a.score for a in alerts) / len(alerts) if alerts else 0
    pdf.key_value("Average Alert Score", f"{avg_score:.1f}")
    pdf.key_value("Total Transaction Volume", f"{total_amount:,.2f}")
    pdf.ln(2)

    # 7. Recommendation
    pdf.section_title("7. Recommendation")
    if case.status == "CLOSED":
        pdf.body_text("Case has been closed. See investigation notes for final disposition.")
    elif any(a.disposition == "sar" for a in alerts):
        pdf.body_text(
            "RECOMMENDATION: File SAR. One or more alerts have been dispositioned for SAR filing."
        )
    elif any(a.disposition == "escalate" for a in alerts):
        pdf.body_text("RECOMMENDATION: Escalate for senior review.")
    else:
        pdf.body_text(
            "RECOMMENDATION: Continue investigation. "
            "Review transaction patterns and alert details above."
        )

    # 8. Investigation Notes
    if notes:
        pdf.section_title("8. Investigation Notes")
        for n in notes:
            ts = n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else "N/A"
            pdf.set_font("Helvetica", "I", 9)
            pdf.cell(0, 5, f"[{ts}] {n.actor}:", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            pdf.body_text(n.note)

    # Write PDF
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out))

    return str(out.resolve())
