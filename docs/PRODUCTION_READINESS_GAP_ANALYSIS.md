# Production Readiness + Research-Aligned Gap Analysis

Principal fintech AML engineering lead assessment. Authority: FATF recommendations, EU AMLD, and supervisory expectations for transaction monitoring (operational usability, entity-centric/network analytics, reproducibility and governance).

---

## A) BASELINE INVENTORY (1 page max)

### Current capabilities and locations

| Capability | Location (module / file) |
|------------|-------------------------|
| Ingest (CSV) | `src/aml_monitoring/ingest/csv_ingest.py` — `ingest_csv()` |
| Ingest (JSONL) | `src/aml_monitoring/ingest/jsonl_ingest.py` — `ingest_jsonl()` |
| Idempotency / external_id | `src/aml_monitoring/ingest/_idempotency.py` — `compute_external_id()` |
| Rules engine | `src/aml_monitoring/rules/` — `base.py`, `high_value.py`, `rapid_velocity.py`, `geo_mismatch.py`, `structuring_smurfing.py`, `sanctions_keyword.py`, `high_risk_country.py`; `run_rules.py` |
| Scoring | `src/aml_monitoring/scoring.py` — `compute_transaction_risk()`, bands |
| Alerts | `src/aml_monitoring/models.py` — `Alert`; persisted in `run_rules.py` |
| Reporting (SAR JSON/CSV) | `src/aml_monitoring/reporting.py` — `generate_sar_report()` |
| API | `src/aml_monitoring/api.py` — `/score`, `/alerts`, `/transactions/{id}` |
| CLI | `src/aml_monitoring/cli.py` — ingest, run-rules, generate-reports, serve-api, simulate-stream |
| Audit / repro | `config_hash` in `config.py`; `Transaction`/`Alert`: `config_hash`, `rules_version`, `engine_version`; `AuditLog` in `models.py`; writes in `csv_ingest.py`, `jsonl_ingest.py`, `run_rules.py`, `reporting.py` |

### Current guarantees

| Guarantee | Mechanism (evidence in repo) |
|-----------|------------------------------|
| Idempotency | `compute_external_id()` (canonical hash); ingest checks DB + `seen_in_batch`/`seen_residual`; skip insert if exists. Tests: `tests/test_idempotency.py`, `tests/test_integration.py::test_reingest_*`. |
| Reproducibility | `get_config_hash(config)`; `config_hash`, `rules_version`, `engine_version` on Transaction and Alert; every AuditLog `details_json` includes `config_hash`, `rules_version`, `engine_version`. Tests: `test_integration.py::test_alerts_include_config_hash_and_versions`, `test_audit_logs_created_for_each_stage`. |
| Logging redaction | `src/aml_monitoring/logging_config.py` — `PIIRedactionFilter`, `PII_REDACT_KEYS`, `REDACT_FIELDS`; applied to root and `aml_monitoring` loggers. |
| Schema upgrade gating | `src/aml_monitoring/db.py` — `_missing_columns()`, `_upgrade_schema()`; run only when `sqlite` and `AML_ALLOW_SCHEMA_UPGRADE=true`; else `RuntimeError`. Tests: `tests/test_db_schema_upgrade.py`. |

---

## B) CRITICAL GAP ANALYSIS (ranked, max 10)

1. **No correlation_id or request/run traceability**  
   - **Impact**: Regulators and internal audit require “which run/request produced this decision?”. Without a correlation ID, audit logs cannot be tied to a specific invocation or API request.  
   - **Evidence**: `AuditLog` has no `correlation_id`. All audit writes use hardcoded `actor="system"`. No request-scoped or run-scoped identifier.  
   - **Acceptance criteria**: Every AuditLog row has a non-null `correlation_id`; CLI sets one per run; API sets one per request (from header or generated); actor is set from context (CLI: env `AML_ACTOR` or "cli"; API: header or "api"); tests assert presence and API returns `X-Correlation-ID` in response.

2. **No case management workflow**  
   - **Impact**: Transaction monitoring requires operational usability: alerts must be triaged, assigned, and dispositioned (e.g. close, escalate, SAR).  
   - **Evidence**: No `Case` or `AlertDisposition` model; no states (open, in_review, closed); no assignee; API/CLI do not expose case or workflow.  
   - **Acceptance criteria**: At least one Case entity linked to one-or-many Alerts; state and assignee fields; API/CLI to create/update case and set disposition; tests for state transitions and audit of disposition.

3. **No entity-centric or network model**  
   - **Impact**: Modern AML is entity-centric; risk is assessed across relationships and networks (counterparties, beneficial ownership, clusters).  
   - **Evidence**: No first-class “Entity” or “Relationship” model; counterparty is a string on Transaction; no graph or link analysis.  
   - **Acceptance criteria**: Entity (or equivalent) model with stable id; relationships between entities/accounts; at least one API or report that aggregates by entity/network; tests for entity-level aggregation.

4. **Actor always "system" — no human/system attribution**  
   - **Impact**: Governance requires “who did what” (human vs system, and which identity).  
   - **Evidence**: All `AuditLog(..., actor="system")` in `csv_ingest.py`, `jsonl_ingest.py`, `run_rules.py`, `reporting.py`.  
   - **Acceptance criteria**: Actor set from execution context (CLI env, API header, or default); every audit write uses that actor; tests assert actor value.

5. **No alert disposition or status on Alert**  
   - **Impact**: Alerts must be dispositioned (false positive, escalate, SAR) for regulatory and operational closure.  
   - **Evidence**: `Alert` has no `status` or `disposition` field; no link to Case.  
   - **Acceptance criteria**: Alert has status (e.g. open, closed) and optional disposition; updates audited with correlation_id and actor; tests.

6. **API does not propagate correlation_id to clients**  
   - **Impact**: Clients need to correlate their requests with server-side audit for support and compliance.  
   - **Evidence**: No `X-Correlation-ID` (or similar) in API request/response.  
   - **Acceptance criteria**: API middleware sets correlation_id per request; response includes `X-Correlation-ID`; test asserts header in response.

7. **No change control / versioning for rules logic**  
   - **Impact**: Reproducibility requires knowing which rule code ran; `rules_version` is a single string, not per-rule or code-backed.  
   - **Evidence**: `RULES_VERSION` in `__init__.py`; rules are not versioned individually; no checksum of rule code in audit.  
   - **Acceptance criteria**: Document how rules_version maps to code/deploy; optional per-rule version or code hash in audit details; test that audit contains version info.

8. **Reporting is file-only; no case/alert-centric API**  
   - **Impact**: Case management and integration require fetching alerts/reports by case or correlation.  
   - **Evidence**: `generate_sar_report()` writes files only; no `GET /reports` or `GET /alerts?correlation_id=`.  
   - **Acceptance criteria**: At least one API to list or filter alerts (e.g. by correlation_id); or report metadata in API; tests.

9. **SQLite-only; no migration framework**  
   - **Impact**: Production typically uses PostgreSQL; schema changes need versioned migrations.  
   - **Evidence**: `db.py` uses `Base.metadata.create_all` and optional add-column upgrade; no Alembic or version table.  
   - **Acceptance criteria**: Document path to Postgres (e.g. same SQLAlchemy models); optional Alembic or versioned migrations; SQLite add-column remains for local dev only.

10. **No authentication on API**  
    - **Impact**: Production API must identify the actor (user/service) for audit.  
    - **Evidence**: No auth in `api.py`; no user identity.  
    - **Acceptance criteria**: Auth middleware or document that actor is from `X-Actor` until auth is added; tests for header-based actor when implemented.

---

## C) SINGLE BEST NEXT STEP

**Chosen: (1) correlation_id + actor traceability.**

**Rationale**:  
- Satisfies the non-negotiable that “anything that influences decisions must be reproducible and governed” (audit trail, traceability) without requiring new domain models.  
- Unlocks the fastest path to “bank-real”: every audit log is tied to a run or request and an actor; case management (step 2) can then record “who closed the case” using the same actor/correlation_id.  
- Minimal scope: one new column, one context module, CLI/API context setting, and passing values into existing audit writes.  
- Does not depend on entity model or case model; those are larger follow-ups.

---

## D) IMPLEMENTATION PLAN (correlation_id + actor only)

### File-by-file change list

| File | Change |
|------|--------|
| `src/aml_monitoring/audit_context.py` | **New.** Contextvars for `correlation_id` and `actor`; `set_audit_context(correlation_id, actor)`, `get_audit_context()` returning (correlation_id, actor); `get_correlation_id()` / `get_actor()` that return context or defaults (generate UUID for correlation_id if unset, "system" for actor). |
| `src/aml_monitoring/models.py` | Add `correlation_id: Mapped[str \| None] = mapped_column(String(64), nullable=True, index=True)` to `AuditLog`. |
| `src/aml_monitoring/db.py` | Add `("audit_logs", [("correlation_id", "TEXT")])` to `_SCHEMA_COLUMNS`. |
| `src/aml_monitoring/ingest/csv_ingest.py` | When creating `AuditLog`, set `correlation_id=get_correlation_id()`, `actor=get_actor()`. |
| `src/aml_monitoring/ingest/jsonl_ingest.py` | Same as csv_ingest. |
| `src/aml_monitoring/run_rules.py` | Same. |
| `src/aml_monitoring/reporting.py` | Same. |
| `src/aml_monitoring/cli.py` | After `_ensure_db(config)` in each command, call `set_audit_context(str(uuid.uuid4()), os.environ.get("AML_ACTOR", "cli"))`. |
| `src/aml_monitoring/api.py` | Add middleware: read `X-Correlation-ID` or generate uuid4; read `X-Actor` or use "api"; set audit context; add `X-Correlation-ID` to response headers. |
| `tests/test_audit_context.py` | **New.** Tests: set context and get; default when unset (correlation_id generated, actor "system"). |
| `tests/test_integration.py` | In `test_audit_logs_created_for_each_stage`, set audit context before pipeline; assert each AuditLog row has non-null `correlation_id` and expected `actor`. In `test_report_generation`, optionally set context and assert audit row has correlation_id. |
| `tests/test_api.py` | Test that response has `X-Correlation-ID` header (when client sends it, same value; when not, generated). |
| `tests/test_db_schema_upgrade.py` | Old schema already has no `correlation_id`; `_missing_columns` and upgrade will add it; assert after upgrade `audit_logs` has `correlation_id` (via _missing_columns or pragma). |
| `docs/RULE.md` | Add: Audit log entries must include `correlation_id` and `actor`; CLI uses one correlation_id per run, actor from `AML_ACTOR` or "cli"; API uses request correlation (header or generated) and actor from header or "api". |
| `RUNBOOK.md` | Add: Optional `AML_ACTOR` for CLI; API clients may send `X-Correlation-ID` and `X-Actor`. |

### Data model changes

- **AuditLog**: New column `correlation_id` (String(64), nullable=True, index=True). Existing rows remain null; new rows always populated (from context or generated at write time). No change to `actor` column; we populate it from context instead of hardcoding "system".

### API/CLI changes

- **CLI**: No new flags. Each command sets audit context once at start (correlation_id = uuid4(), actor = env AML_ACTOR or "cli").  
- **API**: Middleware sets context per request; response header `X-Correlation-ID`; optional request header `X-Actor` (and `X-Correlation-ID` to pass through).

### Tests to add/modify

- **New**: `tests/test_audit_context.py` — get/set context; default correlation_id and actor when unset.  
- **Modify**: `test_integration.py::test_audit_logs_created_for_each_stage` — set context, select `AuditLog.correlation_id`, `AuditLog.actor`, assert non-null correlation_id and actor.  
- **Modify**: `test_integration.py::test_report_generation` — after generate_sar_report, query AuditLog for generate_report, assert correlation_id is set (if we set context in test).  
- **Modify**: `test_api.py` — add test that POST /score response includes `X-Correlation-ID`; optionally test that provided `X-Correlation-ID` is echoed.  
- **Modify**: `test_db_schema_upgrade.py` — after upgrade, verify audit_logs has correlation_id column (e.g. _missing_columns returns [] and we can inspect or add a small query).

### Migration/compat notes

- **SQLite**: Schema upgrade adds `correlation_id` when `AML_ALLOW_SCHEMA_UPGRADE=true`. Existing audit_logs rows have null correlation_id; new rows get value.  
- **Postgres later**: Same column; add in migrations when introducing Postgres. No application logic change.

---

## E) APPLY THE CHANGES (diffs)

**Implementation complete.** All file changes applied; `make ci` passes (39 tests). Summary of diffs:

- **New:** `src/aml_monitoring/audit_context.py` — contextvars for correlation_id/actor; `set_audit_context`, `get_audit_context`, `get_correlation_id`, `get_actor`.
- **models.py:** `AuditLog` has `correlation_id: Mapped[str | None]`, nullable, indexed.
- **db.py:** `_SCHEMA_COLUMNS` includes `("audit_logs", [("correlation_id", "TEXT")])`.
- **ingest (csv_ingest.py, jsonl_ingest.py):** AuditLog created with `correlation_id=get_correlation_id()`, `actor=get_actor()`.
- **run_rules.py, reporting.py:** Same for their AuditLog writes.
- **cli.py:** After `_ensure_db`, `set_audit_context(str(uuid.uuid4()), os.environ.get("AML_ACTOR", "cli"))` in ingest, run-rules, generate-reports, simulate-stream.
- **api.py:** `AuditContextMiddleware` sets context from `X-Correlation-ID`/`X-Actor` or defaults; adds `X-Correlation-ID` to response.
- **tests:** New `test_audit_context.py`; integration tests set context and assert correlation_id/actor; API tests assert `X-Correlation-ID` in response and echo when provided.
- **docs/RULE.md, RUNBOOK.md, .env.example:** Audit traceability and AML_ACTOR documented.

---

## F) PROOFREAD & SELF-VERIFY

### Five most likely failure points after changes

1. **Imports**: New `audit_context` used from ingest, run_rules, reporting, cli, api — ensure no circular import (audit_context must not import db or models).  
2. **Test fixtures**: Integration tests that create DB and run pipeline must set audit context so that audit log assertions see correlation_id/actor; test_report_generation may not set context — then we must either set it or allow correlation_id to be generated in get_correlation_id().  
3. **Config mismatch**: No new config keys; AML_ACTOR is env-only. Ensure .env.example documents AML_ACTOR.  
4. **DB state**: Existing SQLite DBs without correlation_id column will get it via upgrade when AML_ALLOW_SCHEMA_UPGRADE=true; tests that use in-memory or tmp DB get the column from create_all (new model).  
5. **API middleware order**: Middleware must run before routes so context is set; and must set response header after request — FastAPI middleware handles this.

### Exact commands to verify from a clean clone

```bash
cd "AML Transaction Monitoring Engine Project"
poetry install
make ci
AML_ALLOW_SCHEMA_UPGRADE=true make run
# Optional: AML_ACTOR=analyst make ingest data/synthetic/transactions.csv
# Optional: curl -i -X POST http://127.0.0.1:8000/score -H "Content-Type: application/json" -d '{"transaction":{"account_id":1,"ts":"2025-01-01T12:00:00Z","amount":100,"currency":"USD"}}' | grep -i x-correlation
```
