# Thread B — Research Auditor + Red Team Review

**Input:** Thread A output (PRODUCTION_READINESS_GAP_ANALYSIS.md + implemented correlation_id/actor + CI 39 tests passing).  
**Role:** Brutal audit; actionable, testable output; no invented sources.

---

## 1) WHAT THREAD A DID RIGHT (max 7 bullets)

- **Delivered the chosen step end-to-end:** correlation_id and actor are in the model, schema upgrade, all audit writers (ingest CSV/JSONL, run_rules, reporting), CLI and API context, and tests; no half-done TODOs.
- **Audit context is correctly isolated:** `audit_context.py` uses contextvars only and does not import db/models, avoiding circular deps and keeping traceability separate from persistence.
- **Schema upgrade gating is preserved:** `correlation_id` was added via the existing `_SCHEMA_COLUMNS` / `_upgrade_schema()` path; no new mechanism; test_db_schema_upgrade still validates upgrade-with-flag and reject-without-flag.
- **API middleware is correctly ordered:** `AuditContextMiddleware` runs before routes, sets context per request, and adds `X-Correlation-ID` to the response; tests assert header presence and echo when client sends it.
- **Integration tests enforce traceability:** `test_audit_logs_created_for_each_stage` sets context and asserts every AuditLog row has non-null `correlation_id`, expected actor, and details_json with config_hash; `test_report_generation` asserts correlation_id/actor on generate_report audit row.
- **Docs and runbook are aligned:** RULE.md and RUNBOOK.md describe correlation_id/actor, AML_ACTOR, X-Correlation-ID/X-Actor; .env.example documents AML_ACTOR and schema upgrade.
- **Single, scoped next step:** Thread A chose one step (correlation_id + actor), implemented it fully, and did not mix in case management, entity model, or auth.

---

## 2) WHAT THREAD A DID WRONG / MISSED (ranked, exactly 10 bullets)

1. **GET /alerts does not support filtering by correlation_id**  
   - **Impact:** Clients and support cannot retrieve “all alerts from this run/request”; traceability is write-only and not operationally usable.  
   - **Evidence:** Gap #8 in PRODUCTION_READINESS_GAP_ANALYSIS.md requires “at least one API to list or filter alerts (e.g. by correlation_id)”; `api.py` list_alerts has only `limit` and `severity` (lines 147–161).  
   - **Fix principle:** Add optional `correlation_id` query param to GET /alerts; filter AuditLog or join Alert to the run that created it — requires Alert.correlation_id or query audit_logs by correlation_id + entity_type=run_rules to get scope, then filter alerts by that run (or add correlation_id to Alert when created in run_rules and filter directly).

2. **Alert has no status or disposition; no way to close or classify alerts**  
   - **Impact:** Every alert is perpetually “open”; no false positive / escalate / SAR tracking; regulators and ops require disposition for closure.  
   - **Evidence:** Gap #5 in doc; `models.py` Alert (lines 67–82) has no status/disposition; no API or CLI to set disposition.  
   - **Fix principle:** Add Alert.status (e.g. open/closed) and optional disposition (e.g. false_positive, escalate, sar); persist with audit (correlation_id, actor); API/CLI to update and tests for state + audit.

3. **No case management workflow**  
   - **Impact:** Alerts cannot be grouped into cases, assigned, or progressed through a workflow (open → in_review → closed); required for operational AML.  
   - **Evidence:** Gap #2; no Case or AlertDisposition model; no assignee/state in repo.  
   - **Fix principle:** Introduce at least one Case entity linked to alerts; state and assignee; API/CLI to create/update case and set disposition; audit case actions with correlation_id/actor.

4. **No entity-centric or network model**  
   - **Impact:** Risk cannot be assessed at entity or network level; counterparty is a string on Transaction only.  
   - **Evidence:** Gap #3; no Entity/Relationship model; no aggregation by entity in API or reporting.  
   - **Fix principle:** Add Entity (or equivalent) with stable id; relationships; at least one API or report aggregating by entity; tests.

5. **Rules versioning is not code-backed or per-rule**  
   - **Impact:** Reproducibility is ambiguous; cannot prove which rule code produced an alert.  
   - **Evidence:** Gap #7; RULES_VERSION in __init__.py is a single string; no per-rule version or checksum in audit details.  
   - **Fix principle:** Document mapping of rules_version to deploy/code; optionally add per-rule version or code hash to audit details_json; test that audit contains version info.

6. **API does not write AuditLog**  
   - **Impact:** Any future API that creates or updates data (e.g. disposition) will need to log; today no API path writes AuditLog, so pattern is missing.  
   - **Evidence:** Grep on api.py for AuditLog/audit_log returns no matches; only CLI-triggered ingest/run_rules/reporting write AuditLog.  
   - **Fix principle:** When adding mutation endpoints (e.g. PATCH alert disposition), create AuditLog rows with get_correlation_id()/get_actor() and document pattern in RULE.md.

7. **No authentication on API**  
   - **Impact:** Actor is only from headers; any client can send any X-Actor; not acceptable for production.  
   - **Evidence:** Gap #10; api.py has no auth middleware; RUNBOOK/RULE document header-based actor only.  
   - **Fix principle:** Add auth middleware or document that actor is best-effort until auth is implemented; tests for header-based actor when present.

8. **SQLite-only; no versioned migrations**  
   - **Impact:** Production typically uses PostgreSQL; schema changes need repeatable, versioned migrations.  
   - **Evidence:** Gap #9; db.py uses create_all + add-column upgrade only; no Alembic or version table.  
   - **Fix principle:** Document path to Postgres (same models); introduce Alembic or versioned migrations for production; keep SQLite add-column for local dev only.

9. **Simulate stream uses one correlation_id per full run**  
   - **Impact:** Acceptable for “one run” semantics, but if batches are intended to be distinct operations, they are not distinguishable in audit.  
   - **Evidence:** cli.py simulate_stream sets context once (line 112); simulate.py calls ingest in a loop with no new set_audit_context per batch.  
   - **Fix principle:** Either document “one correlation_id per stream run” as intended, or add option to set new correlation_id per batch and document when to use it.

10. **Schema upgrade test does not explicitly assert audit_logs.correlation_id**  
    - **Impact:** If someone removes correlation_id from _SCHEMA_COLUMNS but leaves it on the model, test still passes (missing columns become empty only for the columns still in _SCHEMA_COLUMNS).  
    - **Evidence:** test_db_schema_upgrade.py asserts missing == [] after upgrade but does not query PRAGMA table_info(audit_logs) for correlation_id.  
    - **Fix principle:** Add an explicit assertion that audit_logs has a correlation_id column after upgrade (e.g. column names from PRAGMA or from _get_existing_columns).

---

## 3) TOP 5 GAPS THAT MATTER MOST IN REAL AML (ranked 1–5)

### 1. Alert status and disposition

- **Why it matters:** Regulators and internal audit require that alerts are dispositioned (false positive, escalate, SAR). Without status and disposition, there is no operational closure and no proof of review.
- **Required repo artifacts:**  
  - `src/aml_monitoring/models.py`: Alert.status (e.g. open/closed), Alert.disposition (nullable, e.g. false_positive, escalate, sar).  
  - `src/aml_monitoring/db.py`: _SCHEMA_COLUMNS entries for alerts (status, disposition).  
  - API: PATCH /alerts/{id} or PUT to set status/disposition (and optionally assignee later).  
  - AuditLog written on disposition change with correlation_id, actor, details (old/new status, disposition).  
  - `docs/RULE.md`, RUNBOOK: disposition workflow.  
  - Tests: unit for model, API update, integration for audit of disposition change.
- **Minimum acceptance criteria:** (1) Alert has status and optional disposition; (2) at least one way to update them (API or CLI) with audit; (3) tests assert audit row for disposition change includes correlation_id and actor; (4) make ci passes.
- **Smallest implementation slice:** Add status (default open), disposition (nullable); schema upgrade for alerts; one PATCH /alerts/{id} body { status?, disposition? }; in PATCH handler get session, update alert, write AuditLog(action=disposition_update, ...); tests in test_api.py and test_integration.py.

### 2. GET /alerts filter by correlation_id

- **Why it matters:** Traceability is only useful if operators can fetch “all alerts from this run/request.” Without it, correlation_id is stored but not queryable.
- **Required repo artifacts:**  
  - `src/aml_monitoring/api.py`: list_alerts optional query param correlation_id; filter logic (either Alert.correlation_id if added, or derive from audit_logs / run scope).  
  - Tests: assert GET /alerts?correlation_id=X returns only alerts tied to that run.
- **Minimum acceptance criteria:** GET /alerts accepts optional correlation_id; returns only alerts associated with that correlation_id; test with two runs, two sets of alerts, filter by correlation_id.
- **Smallest implementation slice:** Add correlation_id to Alert when created in run_rules (from get_correlation_id()); add correlation_id to _SCHEMA_COLUMNS for alerts; GET /alerts?correlation_id= filters by Alert.correlation_id; one integration test.

### 3. Case management (minimal)

- **Why it matters:** Alerts must be grouped into cases, assigned, and progressed; this is standard in AML platforms and examiner workflows.
- **Required repo artifacts:** Case model (id, state, assignee, created_at, etc.); link Alert to Case (case_id nullable on Alert or join table); API/CLI to create/update case and attach alerts; audit for case actions.
- **Minimum acceptance criteria:** At least one Case entity; alerts can be associated with a case; state and assignee; API or CLI to create/update; tests.
- **Smallest implementation slice:** Case table; Alert.case_id FK nullable; POST /cases, PATCH /cases/{id}, PATCH /alerts/{id} { case_id }; audit case create/update with correlation_id/actor.

### 4. API authentication and actor binding

- **Why it matters:** In production, actor must be a real identity from auth, not a client-supplied header.
- **Required repo artifacts:** Auth middleware or dependency that sets actor from token/user; document that X-Actor is fallback until auth; tests that actor in audit reflects auth when present.
- **Minimum acceptance criteria:** Documented auth strategy; actor in audit from auth when available; test with mock auth.
- **Smallest implementation slice:** Document in RULE.md and RUNBOOK that production must use auth and bind actor from identity; optional: stub auth dependency that reads header only, with comment that it must be replaced by real auth.

### 5. Versioned schema migrations (Postgres path)

- **Why it matters:** Production DBs need repeatable, versioned migrations; add-column on SQLite is not sufficient for multi-env deployments.
- **Required repo artifacts:** Alembic (or equivalent) env; versioned migration scripts; document that SQLite add-column remains for local dev; same SQLAlchemy models used for Postgres.
- **Minimum acceptance criteria:** One migration that creates/upgrades to current schema; doc describing how to run migrations for Postgres; make ci still passes with SQLite.

---

## 4) THE SINGLE BEST NEXT STEP (exactly one)

**Chosen: Alert status and disposition (with audit).**

- **Why this step unlocks the fastest path to an operational AML system:** Regulators and audit require that every alert is reviewed and dispositioned (false positive, escalate, SAR). Today every alert is implicitly “open” forever; adding status and disposition is the minimal change that enables triage and closure and satisfies the “operational usability” requirement from the gap doc. Case management (gap 2) and GET /alerts?correlation_id= (gap 8) build on top of “we can close and classify alerts.”
- **Why other steps must wait:** GET /alerts?correlation_id= improves traceability retrieval but does not by itself close the regulatory gap of “no disposition.” Case management is larger (new entity, workflow); it is more impactful after alerts can be dispositioned. Auth and Postgres migrations are necessary for production but do not unblock the core AML workflow of “review and disposition alerts.”

---

## 5) CURSOR PROMPT (ONE STEP ONLY)

Use this prompt in Cursor to implement only the chosen step (Alert status and disposition with audit).

```
Implement Alert status and disposition with audit traceability. No other features.

Requirements:
- Add to Alert model: status (str, default "open"; allow "open" | "closed") and disposition (str | None; allow None | "false_positive" | "escalate" | "sar").
- Add these columns to SQLite schema upgrade in db.py (_SCHEMA_COLUMNS for alerts: status, disposition).
- Add PATCH /alerts/{id} that accepts JSON body { "status": optional str, "disposition": optional str }; validate allowed values; update Alert and write one AuditLog row with action="disposition_update", entity_type="alert", entity_id=str(alert_id), correlation_id=get_correlation_id(), actor=get_actor(), details_json with old/new status and disposition, config_hash.
- API middleware already sets audit context; use get_correlation_id() and get_actor() in the PATCH handler.
- Add tests: (1) test_api.py: PATCH /alerts/{id} with status=closed and disposition=false_positive returns 200 and GET /alerts shows updated values; (2) test_integration.py or test_api.py: after PATCH, query AuditLog for action=disposition_update and assert correlation_id and actor are set and details_json contains old/new.
- Update docs/RULE.md and RUNBOOK.md: document alert status and disposition; PATCH /alerts/{id} and that disposition changes are audited.
- No new dependencies. Use existing patterns: Poetry, Makefile, contextvars audit context, schema upgrade gating. No TODOs; no refactors beyond this scope.

Acceptance criteria:
- make ci passes (lint + tests).
- Alert has status and disposition; PATCH updates them and writes an audited disposition_update log entry with correlation_id and actor.
```

---

## 6) VERIFICATION COMMANDS

Run from a clean clone to verify the change (after applying the Cursor prompt above):

```bash
cd "AML Transaction Monitoring Engine Project"
poetry install
make ci
```

Then:

```bash
# Optional: ensure schema upgrade adds new columns (if using existing DB)
AML_ALLOW_SCHEMA_UPGRADE=true poetry run aml ingest data/synthetic/transactions.csv
AML_ALLOW_SCHEMA_UPGRADE=true poetry run aml run-rules
# Start API and test PATCH
AML_ALLOW_SCHEMA_UPGRADE=true poetry run aml serve-api &
sleep 2
# Get first alert id (if any)
ALERT_ID=$(curl -s "http://127.0.0.1:8000/alerts?limit=1" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if d else '')")
# If alert exists, PATCH disposition
[ -n "$ALERT_ID" ] && curl -s -X PATCH "http://127.0.0.1:8000/alerts/$ALERT_ID" -H "Content-Type: application/json" -d '{"status":"closed","disposition":"false_positive"}' -w "\n%{http_code}\n"
kill %1 2>/dev/null || true
```

For automated verification (no manual PATCH), running `make ci` after the implementation is sufficient.
