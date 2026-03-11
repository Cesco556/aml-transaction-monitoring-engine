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


@app.command("train-ml")
def train_ml_cmd(
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
) -> None:
    """Train the ML anomaly detection model on current transaction data."""
    _ensure_db(config)
    set_audit_context(str(uuid.uuid4()), os.environ.get("AML_ACTOR", "cli"))

    try:
        from aml_monitoring.ml.anomaly import train_anomaly_model
    except ImportError:
        typer.echo(
            "ML dependencies not installed (scikit-learn, joblib). "
            "Install with: poetry add scikit-learn joblib",
            err=True,
        )
        raise typer.Exit(1)

    cfg = get_config(config)
    ml_cfg = cfg.get("ml", {}).get("anomaly_detection", {})
    if not ml_cfg:
        typer.echo("No ml.anomaly_detection section in config.", err=True)
        raise typer.Exit(1)

    with session_scope() as session:
        try:
            result = train_anomaly_model(session, ml_cfg)
        except ValueError as e:
            typer.echo(f"Training failed: {e}", err=True)
            raise typer.Exit(1)

        # Audit trail
        session.add(
            AuditLog(
                correlation_id=get_correlation_id(),
                action="ml_model_train",
                entity_type="ml_model",
                entity_id=result["data_hash"],
                actor=get_actor(),
                details_json={
                    "model_path": result["model_path"],
                    "sample_count": result["sample_count"],
                    "feature_count": result["feature_count"],
                    "anomaly_ratio": round(result["anomaly_ratio"], 4),
                    "data_hash": result["data_hash"],
                },
            )
        )

    typer.echo("ML model trained successfully:")
    typer.echo(f"  Model path:    {result['model_path']}")
    typer.echo(f"  Samples:       {result['sample_count']}")
    typer.echo(f"  Features:      {result['feature_count']}")
    typer.echo(f"  Anomaly ratio: {result['anomaly_ratio']:.4f}")
    typer.echo(f"  Data hash:     {result['data_hash']}")


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


@app.command("screen-name")
def screen_name_cmd(
    name: str = typer.Argument(..., help="Name to screen against all loaded lists"),
    threshold: float = typer.Option(0.80, "--threshold", "-t", help="Minimum match threshold"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
) -> None:
    """Screen a single name against all loaded sanctions and PEP lists."""
    cfg = get_config(config)
    sanctions_cfg = cfg.get("sanctions", {})

    try:
        from aml_monitoring.sanctions.lists import SanctionsList
        from aml_monitoring.sanctions.ofac import parse_sdn_csv
        from aml_monitoring.sanctions.pep import PEPList
    except ImportError:
        typer.echo(
            "Sanctions module not available. Install rapidfuzz and jellyfish.",
            err=True,
        )
        raise typer.Exit(1)

    typer.echo(f"Screening name: {name!r} (threshold={threshold})")
    typer.echo("-" * 60)

    # Load sanctions lists
    screening_cfg = sanctions_cfg.get("screening", {})
    lists_cfg = screening_cfg.get("lists", {})
    algorithms = screening_cfg.get("algorithms", ["exact", "jaro_winkler", "levenshtein", "phonetic"])
    hit_count = 0

    for list_name, list_conf in lists_cfg.items():
        if not list_conf.get("enabled", True):
            continue
        path = list_conf.get("path", "")
        fmt = list_conf.get("format", "csv")
        if not path or not Path(path).exists():
            continue
        sl = SanctionsList(source=list_name)
        if fmt == "ofac_csv":
            entries = parse_sdn_csv(path)
            sl.load_entries(entries)
        elif fmt == "json":
            sl.load_json(path)
        else:
            sl.load_csv(path)
        matches = sl.search(name, threshold=threshold, algorithms=algorithms)
        for m in matches:
            hit_count += 1
            typer.echo(
                f"  [SANCTIONS] {m.matched_alias} | list={list_name} | "
                f"score={m.score:.2%} | algo={m.algorithm} | "
                f"type={m.entry.entity_type} | country={m.entry.country}"
            )

    # PEP list
    pep_cfg = sanctions_cfg.get("pep", {})
    if pep_cfg.get("enabled", True):
        pep_path = pep_cfg.get("path", "")
        pep_threshold = float(pep_cfg.get("min_match_threshold", 0.80))
        if pep_path and Path(pep_path).exists():
            pl = PEPList(source="pep")
            pl.load_csv(pep_path)
            matches = pl.search(name, threshold=min(threshold, pep_threshold), algorithms=algorithms)
            for m in matches:
                hit_count += 1
                typer.echo(
                    f"  [PEP] {m.matched_alias} | position={m.entry.position} | "
                    f"score={m.score:.2%} | algo={m.algorithm} | "
                    f"country={m.entry.country} | risk={m.entry.risk_level}"
                )

    typer.echo("-" * 60)
    if hit_count == 0:
        typer.echo("No matches found.")
    else:
        typer.echo(f"Total matches: {hit_count}")


@app.command("load-sanctions")
def load_sanctions_cmd(
    path: str = typer.Argument(..., help="Path to sanctions list file (CSV or JSON)"),
    fmt: str = typer.Option("csv", "--format", "-f", help="File format: csv, json, ofac_csv"),
) -> None:
    """Load and validate a sanctions list file."""
    p = Path(path)
    if not p.exists():
        typer.echo(f"File not found: {path}", err=True)
        raise typer.Exit(1)

    try:
        from aml_monitoring.sanctions.lists import SanctionsList
        from aml_monitoring.sanctions.ofac import parse_sdn_csv
    except ImportError:
        typer.echo("Sanctions module not available.", err=True)
        raise typer.Exit(1)

    sl = SanctionsList(source=p.stem)
    if fmt == "ofac_csv":
        entries = parse_sdn_csv(path)
        sl.load_entries(entries)
    elif fmt == "json":
        sl.load_json(path)
    else:
        sl.load_csv(path)

    typer.echo(f"Loaded {sl.entry_count} entries from {path} (format={fmt})")
    for entry in sl.entries[:5]:
        aliases = ", ".join(entry.aliases[:3]) if entry.aliases else "none"
        typer.echo(f"  {entry.name} [{entry.entity_type}] aliases={aliases}")
    if sl.entry_count > 5:
        typer.echo(f"  ... and {sl.entry_count - 5} more")


@app.command("sanctions-status")
def sanctions_status_cmd(
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
) -> None:
    """Show loaded sanctions lists, entry counts, and configuration."""
    cfg = get_config(config)
    sanctions_cfg = cfg.get("sanctions", {})
    screening_cfg = sanctions_cfg.get("screening", {})

    typer.echo("Sanctions Screening Configuration")
    typer.echo("=" * 50)
    typer.echo(f"  Enabled:    {screening_cfg.get('enabled', False)}")
    typer.echo(f"  Threshold:  {screening_cfg.get('min_match_threshold', 0.85)}")
    typer.echo(f"  Algorithms: {', '.join(screening_cfg.get('algorithms', []))}")
    typer.echo()

    lists_cfg = screening_cfg.get("lists", {})
    typer.echo("Sanctions Lists:")
    for list_name, list_conf in lists_cfg.items():
        enabled = list_conf.get("enabled", True)
        path = list_conf.get("path", "")
        exists = Path(path).exists() if path else False
        count = "?"
        if exists:
            try:
                from aml_monitoring.sanctions.lists import SanctionsList
                from aml_monitoring.sanctions.ofac import parse_sdn_csv

                sl = SanctionsList(source=list_name)
                fmt = list_conf.get("format", "csv")
                if fmt == "ofac_csv":
                    entries = parse_sdn_csv(path)
                    sl.load_entries(entries)
                elif fmt == "json":
                    sl.load_json(path)
                else:
                    sl.load_csv(path)
                count = str(sl.entry_count)
            except Exception:
                count = "error"
        status_icon = "✓" if enabled and exists else "✗"
        typer.echo(f"  {status_icon} {list_name}: {path} ({count} entries, enabled={enabled})")

    pep_cfg = sanctions_cfg.get("pep", {})
    typer.echo()
    typer.echo("PEP Screening:")
    pep_enabled = pep_cfg.get("enabled", False)
    pep_path = pep_cfg.get("path", "")
    pep_exists = Path(pep_path).exists() if pep_path else False
    pep_count = "?"
    if pep_exists:
        try:
            from aml_monitoring.sanctions.pep import PEPList

            pl = PEPList()
            pl.load_csv(pep_path)
            pep_count = str(pl.entry_count)
        except Exception:
            pep_count = "error"
    pep_icon = "✓" if pep_enabled and pep_exists else "✗"
    typer.echo(f"  {pep_icon} PEP: {pep_path} ({pep_count} entries, enabled={pep_enabled})")


@app.command("stream-consume")
def stream_consume_cmd(
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
    backend: str | None = typer.Option(None, "--backend", "-b", help="redis or file"),
    max_messages: int | None = typer.Option(
        None, "--max-messages", "-n", help="Stop after N messages (default: run forever)"
    ),
) -> None:
    """Start the stream consumer (reads transactions, runs rules, creates alerts)."""
    _ensure_db(config)
    set_audit_context(str(uuid.uuid4()), os.environ.get("AML_ACTOR", "cli"))
    cfg = get_config(config)
    stream_cfg = cfg.get("streaming", {})
    be = backend or stream_cfg.get("backend", "file")

    if be == "redis":
        redis_cfg = stream_cfg.get("redis", {})
        try:
            from aml_monitoring.streaming.consumer import RedisStreamConsumer

            consumer = RedisStreamConsumer(
                redis_url=redis_cfg.get("url", "redis://localhost:6379"),
                stream_key=redis_cfg.get("stream_key", "aml:transactions"),
                consumer_group=redis_cfg.get("consumer_group", "aml-workers"),
                consumer_name=redis_cfg.get("consumer_name", "worker-1"),
                config=cfg,
                batch_size=int(redis_cfg.get("batch_size", 10)),
                poll_interval_ms=int(redis_cfg.get("poll_interval_ms", 1000)),
            )
        except ImportError:
            typer.echo(
                "redis package not installed. Use --backend file or install: poetry add redis",
                err=True,
            )
            raise typer.Exit(1)
    else:
        file_cfg = stream_cfg.get("file", {})
        from aml_monitoring.streaming.consumer import FileStreamConsumer

        consumer = FileStreamConsumer(
            input_path=file_cfg.get("input_path", "data/stream/incoming.jsonl"),
            processed_path=file_cfg.get("processed_path", "data/stream/processed.jsonl"),
            config=cfg,
            batch_size=int(stream_cfg.get("redis", {}).get("batch_size", 10)),
        )

    typer.echo(f"Starting stream consumer (backend={be})...")
    consumer.consume(max_messages=max_messages)
    typer.echo(
        f"Consumer stopped: {consumer.processed_count} processed, "
        f"{consumer.alert_count} alerts created."
    )


@app.command("stream-produce")
def stream_produce_cmd(
    path: str = typer.Argument(..., help="Path to JSONL file to publish"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
    backend: str | None = typer.Option(None, "--backend", "-b", help="redis or file"),
) -> None:
    """Publish transactions from a JSONL file to the stream."""
    cfg = get_config(config)
    stream_cfg = cfg.get("streaming", {})
    be = backend or stream_cfg.get("backend", "file")

    if be == "redis":
        redis_cfg = stream_cfg.get("redis", {})
        try:
            from aml_monitoring.streaming.producer import RedisStreamProducer

            producer = RedisStreamProducer(
                redis_url=redis_cfg.get("url", "redis://localhost:6379"),
                stream_key=redis_cfg.get("stream_key", "aml:transactions"),
            )
        except ImportError:
            typer.echo("redis package not installed.", err=True)
            raise typer.Exit(1)
    else:
        file_cfg = stream_cfg.get("file", {})
        from aml_monitoring.streaming.producer import FileStreamProducer

        producer = FileStreamProducer(
            output_path=file_cfg.get("input_path", "data/stream/incoming.jsonl"),
        )

    p = Path(path)
    if not p.exists():
        typer.echo(f"File not found: {path}", err=True)
        raise typer.Exit(1)

    count = 0
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            producer.publish(msg)
            count += 1

    producer.close()
    typer.echo(f"Published {count} messages (backend={be}).")


@app.command("stream-status")
def stream_status_cmd(
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
) -> None:
    """Show stream status (consumer group info, lag, last processed)."""
    cfg = get_config(config)
    stream_cfg = cfg.get("streaming", {})
    be = stream_cfg.get("backend", "file")

    typer.echo(f"Streaming backend: {be}")
    typer.echo(f"Enabled: {stream_cfg.get('enabled', False)}")

    if be == "redis":
        redis_cfg = stream_cfg.get("redis", {})
        try:
            from aml_monitoring.streaming.consumer import RedisStreamConsumer

            consumer = RedisStreamConsumer(
                redis_url=redis_cfg.get("url", "redis://localhost:6379"),
                stream_key=redis_cfg.get("stream_key", "aml:transactions"),
                consumer_group=redis_cfg.get("consumer_group", "aml-workers"),
                consumer_name=redis_cfg.get("consumer_name", "worker-1"),
                config=cfg,
            )
            info = consumer.stream_info()
            consumer.close()

            if "error" in info:
                typer.echo(f"Error: {info['error']}")
            else:
                typer.echo(f"Stream key: {info['stream_key']}")
                typer.echo(f"Stream length: {info['length']}")
                for g in info.get("groups", []):
                    typer.echo(
                        f"  Group: {g.get('name')} | consumers: {g.get('consumers')} | "
                        f"pending: {g.get('pending')} | last-delivered: {g.get('last-delivered-id')}"
                    )
        except ImportError:
            typer.echo("redis package not installed.", err=True)
    else:
        file_cfg = stream_cfg.get("file", {})
        input_path = Path(file_cfg.get("input_path", "data/stream/incoming.jsonl"))
        processed_path = Path(file_cfg.get("processed_path", "data/stream/processed.jsonl"))

        if input_path.exists():
            with open(input_path) as f:
                lines = sum(1 for line in f if line.strip())
            typer.echo(f"Input file: {input_path} ({lines} messages)")
        else:
            typer.echo(f"Input file: {input_path} (not found)")

        if processed_path.exists():
            with open(processed_path) as f:
                processed = sum(1 for line in f if line.strip())
            typer.echo(f"Processed: {processed_path} ({processed} acknowledged)")
        else:
            typer.echo(f"Processed: {processed_path} (not found)")


if __name__ == "__main__":
    app()
