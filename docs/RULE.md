# AML Transaction Monitoring – Rule base (alignment & quality)

Use this as the single source of truth for structure, tooling, and conventions. Every change should stay aligned with it.

## Tooling (run via Poetry)

- **Lint**: `make lint` → `poetry run ruff check src tests scripts` + `poetry run black --check` + `poetry run mypy src`
- **Format**: `make format` → `poetry run black src tests scripts` then `poetry run ruff check ... --fix`
- **Test**: `make test` → `poetry run pytest tests -v`
- **CI**: `make ci` = lint then test (must pass before merge)

Config lives in **pyproject.toml**: ruff (line-length 100, [tool.ruff.lint] for select/ignore), black (100), mypy (non-strict, ignore_missing_imports), pytest (tests, pythonpath=src).

## Code conventions

- **Python**: 3.11+. Use `datetime.now(UTC)` (`from datetime import UTC, datetime`); never `datetime.utcnow()`.
- **Imports**: Absolute from `aml_monitoring.*`. Ruff enforces order (I).
- **Types**: Annotate public APIs; mypy must pass.
- **Idempotency**: Ingest uses `external_id` (canonical hash); skip insert if exists; track `seen_in_batch` to avoid duplicate inserts within same batch (CSV/JSONL).
- **Audit**: `Transaction` and `Alert` carry `config_hash`, `rules_version`, `engine_version`. `Alert.correlation_id` must be set at creation (e.g. from `get_correlation_id()`) for run traceability; `GET /alerts?correlation_id=...` filters by it. AuditLog for ingest, run_rules, generate_report with counts, duration, config_hash. Every AuditLog entry must include `correlation_id` and `actor` for traceability: CLI uses one correlation_id per run, actor from env `AML_ACTOR` or "cli"; API uses request correlation (header `X-Correlation-ID` or generated). **Actor binding (API mutations):** For protected endpoints (POST/PATCH that mutate state), actor is derived from API key identity via `X-API-Key` and is trustworthy; `X-Actor` header is ignored. For GET endpoints, actor remains anonymous. See `audit_context.py` and `auth.py`.
- **Schema**: SQLite schema upgrade only when `AML_ALLOW_SCHEMA_UPGRADE=true`; otherwise raise RuntimeError with clear message. Log WARNING when upgrade runs.
- **PII**: Redact in logging (see logging_config); no PII in audit details beyond hashes/IDs where needed.
- **External ID**: Canonical: UTC ISO for ts, Decimal 2dp for amount, currency upper, counterparty/direction lower+strip.
- **Alert lifecycle**: Alerts have `status` (open | closed, default open) and `disposition` (null | false_positive | escalate | sar). Only these values are allowed. Updates via PATCH /alerts/{id} or CLI `update-alert` must be audited: one AuditLog row per update with action=disposition_update, correlation_id, actor, and details_json (old_status, new_status, old_disposition, new_disposition, config_hash). config_hash from the alert’s transaction when available, else runtime config hash.
- **Case lifecycle**: Cases have `status` (NEW | INVESTIGATING | ESCALATED | CLOSED) and `priority` (LOW | MEDIUM | HIGH). Valid status transitions: NEW → INVESTIGATING, ESCALATED, or CLOSED; INVESTIGATING → ESCALATED or CLOSED; ESCALATED → CLOSED; CLOSED cannot transition. Invalid transitions must return 400 (API) or exit with error (CLI). All case actions (create, update, add note, add item) must be audited: AuditLog with action one of case_create, case_update, case_note_add, case_item_add; every entry must include correlation_id and actor.
- **Network / entity**: RelationshipEdge table holds edges (src_type/src_id → dst_type/dst_key) from transactions (account→counterparty, account→merchant, customer→counterparty). Build via `aml build-network`; writes AuditLog action=network_build with edge_count, duration_seconds, correlation_id, actor. **NetworkRingIndicator** rule: detects ring pattern (accounts sharing ≥ N counterparties with ≥ M linked accounts). Config: `network_ring.enabled`, `min_shared_counterparties`, `min_linked_accounts`, `lookback_days`, `severity`, `score_delta`. Evidence fields: `linked_accounts`, `shared_counterparties`, `overlap_count`, `degree`, `lookback_days`. Fires at most once per account per run.

## Structure

- `src/aml_monitoring/`: audit_context, config, db, models, schemas, logging_config, ingest (csv, jsonl, _idempotency), rules, scoring, run_rules, reporting, case_lifecycle, network (graph_builder, metrics), api, cli, simulate.
- `config/`: default.yaml, dev.yaml.
- `tests/`: conftest (DB url quoted for YAML), test_api (file DB + api_config for lifespan), test_integration, test_idempotency, test_db_schema_upgrade, test_config, test_rules, test_scoring, test_schemas, test_case_lifecycle.
- `scripts/`: generate_synthetic_data.py.
- **Makefile**: install, shell, format, lint, test, ci, run (ingest + run-rules + reports), ingest, run-rules, reports, serve, stream, synthetic. All via `poetry run`; paths use `scripts` and `data/synthetic`.

## Operations

- **RUNBOOK.md**: Quickstart (make install, lint, format, test, ci, shell, full pipeline). Prerequisites, setup, daily ops.
- **Full pipeline**: `make synthetic` → `make run` (ingest, run-rules, reports). Optional: `make serve` (API), `make stream` (simulate stream).
- **Env**: Optional `.env` from `.env.example`. For local SQLite schema upgrade: `AML_ALLOW_SCHEMA_UPGRADE=true`. Optional `AML_ACTOR` for CLI audit traceability. API: `AML_API_KEYS` for mutation auth; clients send `X-API-Key` on PATCH/POST (and optionally `X-Correlation-ID`); response includes `X-Correlation-ID`. GET endpoints are unauthenticated.

## When fixing issues

1. Run `make ci`; fix lint (ruff, black, mypy) then test failures.
2. Prefer `make format` before manual style edits.
3. Keep UTC for all timestamps; no deprecated APIs (e.g. utcnow).
4. Preserve idempotency and audit semantics; do not drop config_hash / rules_version / engine_version from models or audit logs.
5. After changes, re-run `make ci` and optionally `make run` + `make serve` to confirm E2E.
