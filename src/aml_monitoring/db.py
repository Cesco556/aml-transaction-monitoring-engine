"""SQLAlchemy 2.x engine and session (SQLite and Postgres)."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Generator
from contextlib import contextmanager
from logging import getLogger

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from aml_monitoring.models import AuditLog, Base

logger = getLogger(__name__)

# Module-level engine/session_factory; set via init_db()
_engine = None
_SessionLocal: sessionmaker[Session] | None = None

_IS_SQLITE = False

_SCHEMA_COLUMNS = (
    (
        "transactions",
        [
            ("external_id", "TEXT"),
            ("config_hash", "TEXT"),
            ("rules_version", "TEXT"),
            ("engine_version", "TEXT"),
        ],
    ),
    (
        "alerts",
        [
            ("config_hash", "TEXT"),
            ("rules_version", "TEXT"),
            ("engine_version", "TEXT"),
            ("correlation_id", "TEXT"),
            ("status", "TEXT"),
            ("disposition", "TEXT"),
            ("updated_at", "DATETIME"),
        ],
    ),
    (
        "audit_logs",
        [
            ("correlation_id", "TEXT"),
            ("prev_hash", "TEXT"),
            ("row_hash", "TEXT"),
        ],
    ),
)


def _get_existing_columns(conn, table: str) -> set[str]:
    """Return set of column names for table (SQLite pragma_table_info)."""
    r = conn.execute(text(f"PRAGMA table_info({table})"))
    return {row[1] for row in r.fetchall()}


def _missing_columns(engine) -> list[tuple[str, str]]:
    """Return list of (table, column) that are expected but missing."""
    missing: list[tuple[str, str]] = []
    with engine.connect() as conn:
        for table, columns in _SCHEMA_COLUMNS:
            existing = _get_existing_columns(conn, table)
            for col_name, _ in columns:
                if col_name not in existing:
                    missing.append((table, col_name))
    return missing


def _audit_row_canonical(row: AuditLog) -> str:
    """Canonical string for hashing (excludes id, prev_hash, row_hash)."""
    ts_str = row.ts.isoformat() if row.ts else ""
    details = json.dumps(row.details_json or {}, sort_keys=True)
    return f"{row.correlation_id or ''}|{row.action}|{row.entity_type}|{row.entity_id}|{ts_str}|{row.actor}|{details}"


def _compute_audit_chain(session: Session) -> None:
    """Set prev_hash and row_hash on new AuditLog instances (tamper resistance)."""
    new_logs = [o for o in session.new if isinstance(o, AuditLog)]
    if not new_logs:
        return
    prev_hash: str | None = None
    stmt = select(AuditLog.row_hash).order_by(AuditLog.id.desc()).limit(1)
    result = session.execute(stmt).scalar_one_or_none()
    if result is not None:
        prev_hash = result
    for row in new_logs:
        row.prev_hash = prev_hash
        payload = (prev_hash or "") + _audit_row_canonical(row)
        row.row_hash = hashlib.sha256(payload.encode()).hexdigest()
        prev_hash = row.row_hash


def _upgrade_schema(engine) -> list[tuple[str, str]]:
    """Add audit/reproducibility columns if missing (SQLite). Returns list of (table, column) added."""
    added: list[tuple[str, str]] = []
    with engine.connect() as conn:
        for table, columns in _SCHEMA_COLUMNS:
            existing = _get_existing_columns(conn, table)
            for col_name, col_type in columns:
                if col_name in existing:
                    continue
                try:
                    if table == "alerts" and col_name == "status":
                        conn.execute(
                            text(
                                f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type} DEFAULT 'open'"
                            )
                        )
                    else:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
                    added.append((table, col_name))
                except Exception:
                    conn.rollback()
    if added:
        logger.warning(
            "Schema auto-upgrade ran (AML_ALLOW_SCHEMA_UPGRADE=true). Columns added: %s", added
        )
    return added


def init_db(database_url: str, echo: bool = False) -> None:
    """Create engine and session factory. Call once at startup.
    SQLite: create_all + optional schema upgrade gating. Postgres: engine only (schema via Alembic).
    """
    global _engine, _SessionLocal, _IS_SQLITE
    _IS_SQLITE = "sqlite" in database_url
    connect_args = {} if not _IS_SQLITE else {"check_same_thread": False}
    _engine = create_engine(
        database_url,
        echo=echo,
        connect_args=connect_args,
    )
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    from sqlalchemy import event

    @event.listens_for(Session, "before_flush")
    def _before_flush_audit_chain(session, flush_context, instances):
        _compute_audit_chain(session)

    if _IS_SQLITE:
        Base.metadata.create_all(bind=_engine)
        allow_upgrade = os.environ.get("AML_ALLOW_SCHEMA_UPGRADE", "").strip().lower() == "true"
        if allow_upgrade:
            _upgrade_schema(_engine)
        else:
            missing = _missing_columns(_engine)
            if missing:
                raise RuntimeError(
                    "Schema mismatch detected. Set AML_ALLOW_SCHEMA_UPGRADE=true for local dev OR run migrations."
                )
    # Postgres: schema is applied via Alembic (migrate target); do not create_all here


def get_engine():
    """Return the global engine. Raises if init_db() was not called."""
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _SessionLocal


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Provide a transactional scope for a block."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
