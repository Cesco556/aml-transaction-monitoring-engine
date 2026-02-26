"""Typer CLI: ingest, run-rules, generate-reports, serve-api, simulate-stream, update-alert."""

from __future__ import annotations

import csv
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import typer
from sqlalchemy import select

from aml_monitoring.audit_context import get_actor, get_correlation_id, set_audit_context
from aml_monitoring.case_lifecycle import validate_case_status_transition
from aml_monitoring.config import get_config, get_config_hash
from aml_monitoring.db import init_db, session_scope
from aml_monitoring.ingest import ingest_csv, ingest_jsonl
from aml_monitoring.ingest.schema import (
    infer_column_map,
    load_schema_file,
    save_schema_file,
)
from aml_monitoring.logging_config import setup_logging
from aml_monitoring.models import Alert, AuditLog, Case, CaseItem, CaseNote, Transaction
from aml_monitoring.network import build_network
from aml_monitoring.reporting import generate_sar_report
from aml_monitoring.reproduce import reproduce_run
from aml_monitoring.run_rules import run_rules
from aml_monitoring.schemas import ALERT_DISPOSITION_VALUES, ALERT_STATUS_VALUES
from aml_monitoring.tuning import train as train_tuning

app = typer.Typer(help="AML Transaction Monitoring CLI")


def _ensure_db(config_path: str | None = None) -> None:
    config = get_config(config_path)
    db_url = config.get("database", {}).get("url", "sqlite:///./data/aml.db")
    Path(db_url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
    echo = config.get("database", {}).get("echo", False)
    setup_logging(config.get("app", {}).get("log_level", "INFO"))
    init_db(db_url, echo=echo)


@app.command()
def ingest(
    path: str = typer.Argument(..., help="Path to CSV or JSONL file"),
    config: str | None = typer.Option(
        None, "--config", help="Config YAML path (e.g. config/dev.yaml)"
    ),
    encoding: str = typer.Option("utf-8", "--encoding", "-e", help="CSV encoding"),
    save_schema: bool = typer.Option(
        False,
        "--save-schema",
        help="Save inferred column mapping next to the file for future ingests (CSV only)",
    ),
) -> None:
    """Ingest transactions from CSV or JSONL into the database."""
    _ensure_db(config)
    set_audit_context(str(uuid.uuid4()), os.environ.get("AML_ACTOR", "cli"))
    p = Path(path)
    if p.suffix.lower() not in (".csv", ".jsonl", ".json"):
        typer.echo("File must be .csv or .jsonl", err=True)
        raise typer.Exit(1)
    if p.suffix.lower() == ".csv":
        read, inserted = ingest_csv(
            path, encoding=encoding, config_path=config, save_schema=save_schema
        )
    else:
        read, inserted = ingest_jsonl(path, config_path=config)
    typer.echo(f"Read {read} rows, inserted {inserted} transactions.")


@app.command()
def discover(
    path: str = typer.Argument(..., help="Path to CSV or JSONL file"),
    save: bool = typer.Option(
        False, "--save", "-s", help="Save inferred mapping to a .schema.json file next to the data"
    ),
    encoding: str = typer.Option("utf-8", "--encoding", "-e", help="CSV encoding"),
) -> None:
    """
    Learn from the data: infer column mapping from file headers (and optionally save it).
    Future ingests of the same file will use the saved schema if present, so the engine
    adapts to your data without code changes. Run with --save to persist the mapping.
    """
    p = Path(path)
    if not p.exists():
        typer.echo(f"File not found: {path}", err=True)
        raise typer.Exit(1)
    if p.suffix.lower() not in (".csv", ".jsonl", ".json"):
        typer.echo("File must be .csv or .jsonl", err=True)
        raise typer.Exit(1)
    headers: list[str] = []
    if p.suffix.lower() == ".csv":
        with open(p, encoding=encoding, newline="") as f:
            reader = csv.DictReader(f)
            headers = [h for h in (reader.fieldnames or []) if h]
    else:
        with open(p, encoding=encoding) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                headers = list(obj.keys()) if isinstance(obj, dict) else []
                break
    if not headers:
        typer.echo("No headers found.", err=True)
        raise typer.Exit(1)
    existing = load_schema_file(p)
    column_map = (
        infer_column_map(headers, None) if save else (existing or infer_column_map(headers, None))
    )
    typer.echo(f"Headers ({len(headers)}): {', '.join(headers)}")
    typer.echo("Column mapping (external -> canonical):")
    for ext, canonical in sorted(column_map.items()):
        typer.echo(f"  {ext!r} -> {canonical!r}")
    if save:
        out_path = save_schema_file(p, column_map, headers)
        typer.echo(f"Saved schema to {out_path}")
    elif existing:
        typer.echo(
            "(Existing schema file present; use ingest to load it, or overwrite with --save)"
        )


@app.command("run-rules")
def run_rules_cmd(
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
    resume: bool = typer.Option(
        False, "--resume", help="Resume from last checkpoint for given correlation_id"
    ),
    correlation_id: str | None = typer.Option(
        None,
        "--correlation-id",
        help="Correlation ID of run to resume (required if --resume)",
    ),
) -> None:
    """Run detection rules on all transactions and persist alerts. Use --resume --correlation-id to continue after failure."""
    _ensure_db(config)
    resume_flag = resume is True or (
        isinstance(resume, str) and resume.lower() in ("true", "1", "yes")
    )
    if resume_flag and not correlation_id:
        typer.echo("When using --resume you must provide --correlation-id.", err=True)
        raise typer.Exit(1)
    cid = correlation_id if resume_flag else str(uuid.uuid4())
    set_audit_context(cid, os.environ.get("AML_ACTOR", "cli"))
    processed, alerts = run_rules(
        config_path=config,
        resume_from_correlation_id=cid if resume_flag else None,
    )
    typer.echo(f"Processed {processed} transactions, created {alerts} alerts.")
    if not resume_flag:
        typer.echo(f"Correlation ID: {cid}")


@app.command("build-network")
def build_network_cmd(
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
) -> None:
    """Build/update relationship edges from transactions (audited)."""
    _ensure_db(config)
    set_audit_context(str(uuid.uuid4()), os.environ.get("AML_ACTOR", "cli"))
    result = build_network(config_path=config)
    typer.echo(
        f"Network build complete: {result['edge_count']} edges "
        f"({result['duration_seconds']:.2f}s)."
    )


@app.command()
def train(
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
    output: str | None = typer.Option(
        "config/tuned.yaml", "--output", "-o", help="Path to write tuned config"
    ),
) -> None:
    """Train thresholds from ingested transactions; write config/tuned.yaml (merged on next run)."""
    _ensure_db(config)
    set_audit_context(str(uuid.uuid4()), os.environ.get("AML_ACTOR", "cli"))
    tuned = train_tuning(config_path=config, output_path=output or "config/tuned.yaml")
    typer.echo("Tuned thresholds written. Next run-rules will use them.")
    for rule_name, params in (tuned.get("rules") or {}).items():
        typer.echo(f"  {rule_name}: {params}")


@app.command("generate-reports")
def generate_reports_cmd(
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
    output_dir: str | None = typer.Option(None, "--output", "-o", help="Output directory"),
) -> None:
    """Generate SAR-like reports (JSON + CSV)."""
    _ensure_db(config)
    set_audit_context(str(uuid.uuid4()), os.environ.get("AML_ACTOR", "cli"))
    cfg = get_config(config)
    out = output_dir or cfg.get("reporting", {}).get("output_dir", "./reports")
    include_evidence = cfg.get("reporting", {}).get("include_evidence", True)
    with session_scope() as session:
        jp, cp = generate_sar_report(
            session, out, include_evidence=include_evidence, config_path=config
        )
    typer.echo(f"Reports: {jp}, {cp}")


@app.command("serve-api")
def serve_api(
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
    host: str | None = typer.Option(None, "--host", "-h", help="Bind host"),
    port: int | None = typer.Option(None, "--port", "-p", help="Bind port"),
) -> None:
    """Start the FastAPI server."""
    cfg = get_config(config)
    h = host or os.environ.get("AML_API_HOST") or cfg.get("api", {}).get("host", "0.0.0.0")
    _pe = os.environ.get("AML_API_PORT", "")
    p = (
        port
        if port is not None
        else (int(_pe) if _pe and _pe.isdigit() else None) or cfg.get("api", {}).get("port", 8000)
    )
    _ensure_db(config)
    import uvicorn

    uvicorn.run(
        "aml_monitoring.api:app",
        host=h,
        port=p,
        reload=False,
    )


@app.command("simulate-stream")
def simulate_stream(
    path: str = typer.Argument(..., help="Path to CSV or JSONL file"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
    delay: float = typer.Option(1.0, "--delay", "-d", help="Delay between batches (seconds)"),
    batch_size: int = typer.Option(10, "--batch-size", "-b", help="Transactions per batch"),
) -> None:
    """Simulate near-real-time ingestion from a file (batch by batch with delay)."""
    from aml_monitoring.simulate import run_stream_simulation

    _ensure_db(config)
    set_audit_context(str(uuid.uuid4()), os.environ.get("AML_ACTOR", "cli"))
    run_stream_simulation(path, config_path=config, delay_seconds=delay, batch_size=batch_size)


@app.command("update-alert")
def update_alert(
    alert_id: int = typer.Option(..., "--id", help="Alert ID to update"),
    status: str | None = typer.Option(None, "--status", help="open | closed"),
    disposition: str | None = typer.Option(
        None, "--disposition", help="false_positive | escalate | sar"
    ),
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
) -> None:
    """Update alert status and/or disposition (audited)."""
    _ensure_db(config)
    set_audit_context(str(uuid.uuid4()), os.environ.get("AML_ACTOR", "cli"))
    if status is not None and status not in ALERT_STATUS_VALUES:
        typer.echo(f"status must be one of {sorted(ALERT_STATUS_VALUES)}", err=True)
        raise typer.Exit(1)
    if disposition is not None and disposition not in ALERT_DISPOSITION_VALUES:
        typer.echo(
            f"disposition must be one of {sorted(ALERT_DISPOSITION_VALUES)}",
            err=True,
        )
        raise typer.Exit(1)
    if status is None and disposition is None:
        typer.echo("Provide at least one of --status or --disposition", err=True)
        raise typer.Exit(1)
    with session_scope() as session:
        alert = session.execute(select(Alert).where(Alert.id == alert_id)).scalar_one_or_none()
        if not alert:
            typer.echo(f"Alert {alert_id} not found", err=True)
            raise typer.Exit(1)
        old_status = alert.status if alert.status else "open"
        old_disposition = alert.disposition
        if status is not None:
            alert.status = status
        if disposition is not None:
            alert.disposition = disposition
        alert.updated_at = datetime.now(UTC)
        new_status = alert.status
        new_disposition = alert.disposition
        row = session.execute(
            select(Transaction.config_hash).where(Transaction.id == alert.transaction_id)
        ).first()
        config_hash = row[0] if row else get_config_hash(get_config(config))
        session.add(
            AuditLog(
                correlation_id=get_correlation_id(),
                action="disposition_update",
                entity_type="alert",
                entity_id=str(alert_id),
                actor=get_actor(),
                details_json={
                    "old_status": old_status,
                    "new_status": new_status,
                    "old_disposition": old_disposition,
                    "new_disposition": new_disposition,
                    "config_hash": config_hash,
                },
            )
        )
    typer.echo(f"Updated alert {alert_id}: status={new_status}, disposition={new_disposition}")


@app.command("create-case")
def create_case_cmd(
    alerts: str | None = typer.Option(None, "--alerts", help="Comma-separated alert IDs"),
    transactions: str | None = typer.Option(
        None, "--transactions", help="Comma-separated transaction IDs"
    ),
    priority: str | None = typer.Option(None, "--priority", help="LOW | MEDIUM | HIGH"),
    assigned_to: str | None = typer.Option(None, "--assigned-to", help="Assignee identifier"),
    note: str | None = typer.Option(None, "--note", help="Optional initial note"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
) -> None:
    """Create a case with optional alert/transaction links and initial note (audited)."""
    from aml_monitoring.case_lifecycle import CASE_PRIORITY_VALUES

    _ensure_db(config)
    set_audit_context(str(uuid.uuid4()), os.environ.get("AML_ACTOR", "cli"))
    if priority is not None and priority not in CASE_PRIORITY_VALUES:
        typer.echo(f"priority must be one of {sorted(CASE_PRIORITY_VALUES)}", err=True)
        raise typer.Exit(1)
    alert_ids = [int(x.strip()) for x in alerts.split(",")] if alerts else []
    transaction_ids = [int(x.strip()) for x in transactions.split(",")] if transactions else []
    cid = get_correlation_id()
    actor = get_actor()
    prio = priority if priority is not None else "MEDIUM"
    with session_scope() as session:
        case = Case(
            status="NEW",
            priority=prio,
            assigned_to=assigned_to,
            correlation_id=cid,
            actor=actor,
        )
        session.add(case)
        session.flush()
        session.add(
            AuditLog(
                correlation_id=cid,
                action="case_create",
                entity_type="case",
                entity_id=str(case.id),
                actor=actor,
                details_json={"priority": prio},
            )
        )
        for aid in alert_ids:
            item = CaseItem(case_id=case.id, alert_id=aid, transaction_id=None)
            session.add(item)
            session.flush()
            session.add(
                AuditLog(
                    correlation_id=cid,
                    action="case_item_add",
                    entity_type="case",
                    entity_id=str(case.id),
                    actor=actor,
                    details_json={"case_item_id": item.id, "alert_id": aid},
                )
            )
        for tid in transaction_ids:
            item = CaseItem(case_id=case.id, alert_id=None, transaction_id=tid)
            session.add(item)
            session.flush()
            session.add(
                AuditLog(
                    correlation_id=cid,
                    action="case_item_add",
                    entity_type="case",
                    entity_id=str(case.id),
                    actor=actor,
                    details_json={"case_item_id": item.id, "transaction_id": tid},
                )
            )
        if note:
            n = CaseNote(case_id=case.id, note=note, actor=actor, correlation_id=cid)
            session.add(n)
            session.flush()
            session.add(
                AuditLog(
                    correlation_id=cid,
                    action="case_note_add",
                    entity_type="case",
                    entity_id=str(case.id),
                    actor=actor,
                    details_json={"case_note_id": n.id},
                )
            )
    typer.echo(f"Created case {case.id} (status=NEW, priority={prio})")


@app.command("update-case")
def update_case_cmd(
    case_id: int = typer.Option(..., "--id", help="Case ID to update"),
    status: str | None = typer.Option(
        None, "--status", help="NEW | INVESTIGATING | ESCALATED | CLOSED"
    ),
    priority: str | None = typer.Option(None, "--priority", help="LOW | MEDIUM | HIGH"),
    assigned_to: str | None = typer.Option(None, "--assigned-to", help="Assignee identifier"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
) -> None:
    """Update case status, priority, or assignment (audited). Status transitions validated."""
    from datetime import UTC

    from aml_monitoring.case_lifecycle import CASE_PRIORITY_VALUES, CASE_STATUS_VALUES

    _ensure_db(config)
    set_audit_context(str(uuid.uuid4()), os.environ.get("AML_ACTOR", "cli"))
    if status is not None and status not in CASE_STATUS_VALUES:
        typer.echo(f"status must be one of {sorted(CASE_STATUS_VALUES)}", err=True)
        raise typer.Exit(1)
    if priority is not None and priority not in CASE_PRIORITY_VALUES:
        typer.echo(f"priority must be one of {sorted(CASE_PRIORITY_VALUES)}", err=True)
        raise typer.Exit(1)
    if status is None and priority is None and assigned_to is None:
        typer.echo("Provide at least one of --status, --priority, or --assigned-to", err=True)
        raise typer.Exit(1)
    with session_scope() as session:
        case = session.execute(select(Case).where(Case.id == case_id)).scalar_one_or_none()
        if not case:
            typer.echo(f"Case {case_id} not found", err=True)
            raise typer.Exit(1)
        if status is not None:
            try:
                validate_case_status_transition(case.status, status)
            except ValueError as e:
                typer.echo(str(e), err=True)
                raise typer.Exit(1) from e
            case.status = status
        if priority is not None:
            case.priority = priority
        if assigned_to is not None:
            case.assigned_to = assigned_to
        case.updated_at = datetime.now(UTC)
        case.correlation_id = get_correlation_id()
        case.actor = get_actor()
        session.add(
            AuditLog(
                correlation_id=get_correlation_id(),
                action="case_update",
                entity_type="case",
                entity_id=str(case_id),
                actor=get_actor(),
                details_json={
                    "status": case.status,
                    "priority": case.priority,
                    "assigned_to": case.assigned_to,
                },
            )
        )
    typer.echo(f"Updated case {case_id}")


@app.command("add-case-note")
def add_case_note_cmd(
    case_id: int = typer.Option(..., "--id", help="Case ID"),
    note: str = typer.Option(..., "--note", help="Note text"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
) -> None:
    """Add a note to a case (audited)."""
    _ensure_db(config)
    set_audit_context(str(uuid.uuid4()), os.environ.get("AML_ACTOR", "cli"))
    with session_scope() as session:
        case = session.execute(select(Case).where(Case.id == case_id)).scalar_one_or_none()
        if not case:
            typer.echo(f"Case {case_id} not found", err=True)
            raise typer.Exit(1)
        cid = get_correlation_id()
        actor = get_actor()
        n = CaseNote(case_id=case_id, note=note, actor=actor, correlation_id=cid)
        session.add(n)
        session.flush()
        session.add(
            AuditLog(
                correlation_id=cid,
                action="case_note_add",
                entity_type="case",
                entity_id=str(case_id),
                actor=actor,
                details_json={"case_note_id": n.id},
            )
        )
    typer.echo(f"Added note to case {case_id}")


@app.command("reproduce-run")
def reproduce_run_cmd(
    correlation_id: str = typer.Argument(..., help="Run correlation_id (UUID) to reproduce"),
    out: str | None = typer.Argument(
        None,
        help="Output JSON path (default: ./reproduce_<correlation_id>.json)",
    ),
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
) -> None:
    """Produce a JSON bundle for a run (audit logs, alerts, cases, network) by correlation_id. Audited."""
    _ensure_db(config)
    set_audit_context(str(uuid.uuid4()), os.environ.get("AML_ACTOR", "cli"))
    path = reproduce_run(correlation_id, out_path=out, config_path=config)
    typer.echo(f"Wrote bundle to {path}")


if __name__ == "__main__":
    app()
