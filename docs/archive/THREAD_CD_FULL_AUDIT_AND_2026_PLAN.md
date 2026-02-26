---
**HISTORICAL (pre-P0–P2 implementation). Current state: see docs/IMPLEMENTATION_DELIVERABLE.md and docs/DOCS_CONSISTENCY_AUDIT.md.**

---
# THREAD C+D — Full Repo Audit, Thread B Verification, 2026 Target State & Remediation Plan

**Role:** 2026-grade AML/FinTech platform architect, auditor, adversarial test lead.  
**Rules:** Repo evidence only; no generic advice; MISSING where evidence absent; smallest credible fixes first; acceptance criteria + tests + verification commands for every change.

---

## 0) REPO EVIDENCE INDEX

Files inspected (exact paths and purpose):

| Path | Purpose |
|------|--------|
| `Makefile` | Targets: install, shell, format, lint, test, ci, run, ingest, run-rules, reports, serve, dashboard, stream, synthetic, migrate, makemigration, demo, demo-down, verify-patch |
| `docker-compose.yml` | Services: postgres, api (uvicorn + alembic), dashboard (streamlit); env AML_API_KEYS |
| `config/default.yaml` | Default rules thresholds, scoring bands, high_risk_country [XX, YY], ingest batch_size |
| `config/dev.yaml` | Dev overrides, high_risk_country [IR, KP, SY, CU] |
| `src/aml_monitoring/__init__.py` | RULES_VERSION = "1.0.0", ENGINE_VERSION = "0.1.0" |
| `src/aml_monitoring/schemas.py` | TransactionCreate, AlertResponse (config_hash, rules_version, engine_version, correlation_id, status, disposition), Case*, SARReportRecord |
| `src/aml_monitoring/models.py` | Customer, Account, Transaction, Alert, Case, CaseItem, CaseNote, RelationshipEdge, AuditLog (prev_hash, row_hash for chain) |
| `src/aml_monitoring/ingest/csv_ingest.py` | ingest_csv; rows_rejected + reject_reasons (missing_iban, parse_error:Type) when rejects; audit details_json (lines 79–81, 94–96, 107–110, 215–226) |
| `src/aml_monitoring/ingest/jsonl_ingest.py` | ingest_jsonl; same rows_rejected/reject_reasons and audit details (77–79, 93–96, 106–109, 214–225) |
| `src/aml_monitoring/ingest/_idempotency.py` | compute_external_id (account_id, ts, amount, currency, counterparty, direction) |
| `src/aml_monitoring/run_rules.py` | run_rules(chunk_size, resume_from_correlation_id); chunk by Transaction.id; checkpoint last_processed_id in AuditLog; evidence_fields include rule_hash |
| `src/aml_monitoring/scoring.py` | normalize_score, score_band(33, 66), compute_transaction_risk(base + deltas) |
| `src/aml_monitoring/config.py` | get_config (YAML + env), validate_high_risk_country (fails on XX/YY), get_config_hash |
| `src/aml_monitoring/auth.py` | parse_api_keys_env (name:key[:scope]), require_api_key, require_api_key_write; scope read_only/read_write |
| `src/aml_monitoring/api.py` | /score, GET /alerts, PATCH /alerts/{id} (require_api_key_write), GET /transactions/{id}, GET /network/account/{id}, GET /health |
| `src/aml_monitoring/cases_api.py` | POST/GET/PATCH /cases, POST /cases/{id}/notes; require_api_key; AuditLog on mutations |
| `src/aml_monitoring/reporting.py` | generate_sar_report (JSON + CSV); Alert+Transaction join; created_at, updated_at, hours_to_disposition in records |
| `src/aml_monitoring/reproduce.py` | reproduce_run: audit_logs, alerts, transactions[] (payloads for alert txns), config.resolved, cases, network edges |
| `src/aml_monitoring/case_lifecycle.py` | CASE_STATUS_VALUES, CASE_PRIORITY_VALUES, VALID_CASE_TRANSITIONS, validate_case_status_transition |
| `src/aml_monitoring/audit_context.py` | ContextVar correlation_id, actor; set_audit_context, get_correlation_id, get_actor |
| `src/aml_monitoring/db.py` | init_db (SQLite create_all + _upgrade_schema gated by AML_ALLOW_SCHEMA_UPGRADE; Postgres no create_all), session_scope |
| `src/aml_monitoring/rules/base.py` | RuleContext, BaseRule (rule_id, RULE_HASH, get_rule_hash(), reset_run_state, evaluate) |
| `src/aml_monitoring/rules/__init__.py` | get_all_rules(config) → list of rule instances from YAML |
| `src/aml_monitoring/rules/high_value.py` | threshold_amount, currency_default; single-txn |
| `src/aml_monitoring/rules/rapid_velocity.py` | min_transactions, window_minutes; count in window |
| `src/aml_monitoring/rules/geo_mismatch.py` | window_minutes, max_countries_in_window; customer-level |
| `src/aml_monitoring/rules/structuring_smurfing.py` | threshold_amount, min_transactions, window_minutes; just-below-threshold count |
| `src/aml_monitoring/rules/sanctions_keyword.py` | keywords, list_version, effective_date in config and evidence_fields |
| `src/aml_monitoring/rules/high_risk_country.py` | countries, list_version, effective_date in config and evidence_fields |
| `src/aml_monitoring/rules/network_ring.py` | ring_signal(account_id, session, lookback_days); uses RelationshipEdge |
| `src/aml_monitoring/network/graph_builder.py` | build_network: all txns in memory; RelationshipEdge (account/customer -> counterparty/merchant) |
| `src/aml_monitoring/network/metrics.py` | ring_signal via RelationshipEdge (src_type=account, dst_type=counterparty) |
| `src/aml_monitoring/tuning.py` | compute_tuned_config (percentiles from txns), write_tuned_config → config/tuned.yaml; no per-rule performance metrics |
| `src/aml_monitoring/cli.py` | ingest, run-rules (--resume, --correlation-id), build-network, train, generate-reports, serve-api, simulate-stream, update-alert, create-case, update-case, add-case-note, reproduce-run |
| `alembic/versions/3bd1dea572a9_initial_schema.py` | Full schema: customers, accounts, transactions, alerts, cases, case_items, case_notes, relationship_edges, audit_logs |
| `scripts/demo.sh` | docker compose up; migrate; generate_synthetic_data; ingest; build-network; run-rules; generate-reports; PATCH alert; POST case; reproduce-run |
| `scripts/generate_synthetic_data.py` | random.seed(42); CSV + JSONL; high-value, sanctions, high-risk country, velocity, structuring, ring patterns |
| `tests/conftest.py` | config_path (tmp), db_session, sample_customer_and_account |
| `tests/test_integration.py` | ingest+run_rules, idempotency, config_hash/versions on alerts, audit_logs per stage, report, network_ring, reproduce_run |
| `tests/test_rules.py` | high_value, sanctions_keyword, high_risk_country unit tests |
| `tests/test_scoring.py` | (referenced in glob; logic in scoring.py) |
| `docs/scenario_library.md` | Typology → expected_rule or OUT_OF_SCOPE; adversarial/determinism coverage |
| `tests/test_run_rules.py` | test_chunk_sizes_produce_identical_alerts, test_resume_no_duplicates_no_skips |
| `tests/test_audit_chain.py` | test_audit_log_has_prev_hash_and_row_hash, test_audit_chain_verification, test_tampering_breaks_verification |
| `tests/test_adversarial_evasion.py` | test_evasion_structuring_just_under_triggers_rule, test_evasion_smurfing_velocity_triggers_rule |
| `tests/test_determinism.py` | test_same_input_twice_same_alert_set |
| `alembic/versions/a1b2c3d4e5f6_audit_log_hash_chain.py` | Adds prev_hash, row_hash to audit_logs |

---

## 1) CURRENT STATE SYSTEM MAP

### Architecture & runtime

- **Components:** Single-process Python app (Typer CLI + FastAPI API). No separate queue/worker; CLI commands run ingest → build-network → run-rules → generate-reports sequentially. Docker: postgres + api (Alembic + uvicorn) + dashboard (Streamlit).
- **DB:** SQLite (default) or PostgreSQL via DATABASE_URL/AML_DATABASE_URL. Schema via Alembic (Postgres) or create_all + optional _upgrade_schema (SQLite, gated by AML_ALLOW_SCHEMA_UPGRADE).
- **APIs:** REST: /score (POST), /alerts (GET, PATCH), /transactions/{id} (GET), /cases (POST, GET, PATCH), /cases/{id}/notes (POST). Auth: X-API-Key → actor; no scopes.
- **CLI:** `aml ingest`, `aml run-rules`, `aml build-network`, `aml train`, `aml generate-reports`, `aml serve-api`, `aml simulate-stream`, `aml update-alert`, `aml create-case`, `aml update-case`, `aml add-case-note`, `aml reproduce-run`.
- **Dataflow:** Ingest (CSV/JSONL) → normalize in-memory → _ensure_customer_and_account → compute_external_id → insert Transaction (dedupe by external_id). Build-network: load all Transaction → aggregate edges → upsert RelationshipEdge. Run-rules: load all Transaction in one session → for each txn evaluate all rules → persist Alert + risk_score on Transaction. Reports: query Alert+Transaction → write JSON/CSV. Reproduce: query by correlation_id → write bundle (audit_logs, alerts, cases, edges; no transaction rows).
- **Error handling:** Ingest: bad row → `except (ValueError, KeyError): continue` (CSV) or same (JSONL); no reject count or reason stored. Run-rules: no per-txn try/except; session rollback on exception. API: HTTPException 400/401/404.

### Data & schemas

- **Transaction:** account_id, ts, amount, currency, merchant, counterparty (string), country, channel, direction, metadata_json, risk_score, config_hash, rules_version, engine_version, external_id (optional, unique). Required for ingest: iban_or_acct (→ account), ts, amount; currency default USD; country default XXX; customer_name default "Unknown".
- **Entity:** No separate Entity table; counterparty is string on Transaction; Customer/Account exist; no entity resolution.
- **Alert:** transaction_id, rule_id, severity, score, reason, evidence_fields (JSON), config_hash, rules_version, engine_version, correlation_id, status (open/closed), disposition (false_positive/escalate/sar), created_at, updated_at.
- **Case:** status (NEW, INVESTIGATING, ESCALATED, CLOSED), priority (LOW, MEDIUM, HIGH), assigned_to, correlation_id, actor; CaseItem (alert_id, transaction_id), CaseNote (note, actor, correlation_id).
- **AuditLog:** correlation_id, action, entity_type, entity_id, ts, actor, details_json. No hash chain or signature.
- **SAR report:** alert_id, transaction_id, rule_id, severity, reason, amount, currency, ts, account_id, counterparty, country, evidence (optional). No timeliness fields (e.g. alert created_at → disposition_at).
- **Validation:** Pydantic for API (TransactionCreate amount bounds, currency length, direction pattern). Ingest: no full schema validation; parse/validation failures increment rows_rejected and append reason (missing_iban, parse_error:ExceptionType); persisted in audit details_json when rows_rejected > 0.
- **Dedupe/idempotency:** external_id = SHA256(account_id | ts_utc_iso | amount_2dp | currency | counterparty | direction); skip if exists or in-batch duplicate.
- **Timestamp/timezone:** _parse_ts accepts several formats; naive datetimes used; UTC applied in some places (e.g. reporting isoformat). No explicit timezone column.
- **Currency:** 3-char; no ISO validation in ingest; schema Field min_length=3 max_length=3 for API.
- **Bad rows:** Rejected rows are counted (rows_rejected) and reasons listed (reject_reasons, cap 500); persisted in ingest audit details_json. Not quarantined to table/file; no per-row reject log.
- **PII:** customer_name, counterparty, merchant stored in plaintext; no redaction/masking in reports or logs documented.

### Detection engine

- **Rules:** HighValueTransaction, RapidVelocity, GeoMismatch, StructuringSmurfing, SanctionsKeywordMatch, HighRiskCountry, NetworkRingIndicator. All defined in code; enabled and params from config (rules.*).
- **Thresholds/parameters:** In config/default.yaml (e.g. high_value.threshold_amount: 10000, rapid_velocity.min_transactions: 5, sanctions_keyword.keywords list, high_risk_country.countries: [XX, YY], network_ring.min_shared_counterparties: 2).
- **Rule evaluation:** get_all_rules(config) → list; for each transaction, for each rule evaluate(ctx); no short-circuit; order fixed by get_all_rules. correlation_id set once per run_rules batch.
- **Explainability:** evidence_fields on Alert (rule-specific dict, e.g. amount/threshold, count/window_minutes, linked_accounts/shared_counterparties).
- **Graph/network:** RelationshipEdge built by build_network; only NetworkRingIndicator uses it (via ring_signal). Other rules use Transaction/customer only; counterparty is string.

### Scoring & prioritisation

- **Formula:** base_risk (from Customer.base_risk or config base_risk_per_customer) + sum(rule score_delta); clamp to [0, max_score]; band by thresholds low/medium/high (default 33, 66).
- **Segment-aware:** No; same formula for all customer types, products, channels.
- **Calibration:** Heuristic only; no backtest or effectiveness metrics.
- **Risk ratings:** Customer.base_risk (default 10); no separate geo risk or product risk tables.

### Case management & workflow

- **Dispositions:** Alert: status open/closed; disposition false_positive, escalate, sar. Case: status NEW→INVESTIGATING→ESCALATED→CLOSED (validated); priority LOW/MEDIUM/HIGH.
- **Assignment:** Case.assigned_to, optional; no queue or round-robin.
- **Escalation:** Status ESCALATED; no automatic escalation rules or SLA.
- **QA sampling:** None.
- **Evidence bundles:** Reproduce bundle by correlation_id (alerts, cases, edges, audit); no transaction payloads → cannot replay without DB.
- **Time metrics:** No alert created_at→disposition time, no escalation timing, no SAR-ready metric stored or reported.

### Reporting & SAR pack

- **SAR report:** JSON (generated_at, alerts array with alert_id, transaction_id, rule_id, severity, reason, evidence, amount, currency, ts, account_id, counterparty, country) and CSV (same minus evidence). Written to output_dir with timestamp suffix.
- **Reproduce bundle:** metadata (timestamp, correlation_id), config (config_hashes, rules_versions, engine_versions), audit_logs, alerts, cases, network (edge_count, edges). No transactions array → replay requires same DB or separate transaction export.
- **Replay:** Not deterministic from bundle alone; bundle has alert transaction_id but not transaction row data.
- **Audit trail:** Alert has config_hash, rules_version, engine_version; report and audit_log carry same. Auditor can trace alert to run (correlation_id) and config hash; rule code version is single RULES_VERSION, not per-rule hash.

### Ops, reliability, scale

- **Logging:** logging_config.setup_logging(log_level); standard logger in modules.
- **Monitoring/metrics:** None (no Prometheus/health endpoint beyond API availability).
- **Health checks:** docker-compose postgres pg_isready; no /health on API.
- **Retry/backoff:** None in ingest or run_rules.
- **Dead-letter:** None.
- **Performance:** run_rules and build_network load all transactions into memory; no chunking, no backpressure, no checkpoint/resume.

### Security

- **Authn/authz:** API key via X-API-Key; actor = key identity (name in AML_API_KEYS). No roles or scopes.
- **Secrets:** API keys from env AML_API_KEYS; .env.example; no vault reference.
- **Config:** YAML + env; no explicit env separation (e.g. prod vs dev) beyond config file path.
- **Data retention/deletion:** Not implemented; no retention policy or purge capability.
- **Audit tamper resistance:** AuditLog append-only at app level; no hash chain, no signature.

### Testing & reproducibility

- **Unit/integration/e2e:** tests/test_*.py; conftest with tmp config and in-memory DB; test_integration covers ingest, run_rules, audit, report, network_ring, reproduce. test_rules: high_value, sanctions, high_risk_country.
- **Deterministic seeds:** generate_synthetic_data.py uses random.seed(42).
- **Golden files:** No golden-file tests for SAR or reproduce output.
- **Same input twice:** Idempotent ingest (external_id); run_rules deterministic for same DB state and config; no test asserting identical alert IDs/reports for two identical runs.

---

## 2) THREAD B HYPOTHESES VERIFIED

| # | Hypothesis | Status | Evidence | Why it matters | Smallest credible fix | Tests to add | Acceptance criteria | Verification commands |
|---|------------|--------|----------|----------------|------------------------|--------------|---------------------|------------------------|
| 1 | Data quality invisible: ingest uses except: continue and drops bad rows silently | **FIXED** | **Now:** csv_ingest 79–81, 94–96, 107–110, 215–226: rows_rejected and reject_reasons (missing_iban, parse_error:Type) written to audit details_json when rejects occur. jsonl_ingest 77–79, 93–96, 106–109, 214–225: same. Tests: test_ingest_rejects.py. | Silent data loss broke audit/MI; fix gives reject counts and reasons. Remaining: no quarantine table/file; no replay of rejects. | Optional: quarantine table or reject file; replay command. | test_ingest_rejects.py asserts details_json. | rows_rejected and reject_reasons in ingest audit when rejects > 0. | `make test`; `make test-ingest-rejects` |
| 2 | Rules not tunable/explainable: thresholds in YAML; no per-rule performance/tuning evidence | **PARTIAL** | Thresholds in config/*.yaml; tuning.py writes tuned.yaml from percentiles; no per-rule precision/recall or tuning_history. Evidence_fields on Alert exist (explainable). | Tuning without effectiveness evidence is blind; auditors want proof that thresholds are justified. | Add tuning_history (e.g. date, rule_id, params, optional effectiveness snapshot); document in TUNING.md; optional rule_register with last_tested. | Integration: run train, assert tuned.yaml; optional test that tuning_history file exists after train. | tuning_history or rule_register updated on train; params documented. | `aml train`; check config/tuned.yaml and optional tuning_history |
| 3 | Scoring uncalibrated: additive base+deltas; fixed bands; no segmentation | **VERIFIED** | `scoring.py`: base + sum(score_delta), normalize_score, score_band(low=33, medium=66). No segment (customer type, product, channel). | Uncalibrated scores and one-size-fits-all bands undermine risk-based prioritisation. | Document as heuristic in DATA_QUALITY.md or scoring doc; add optional segment key to scoring (e.g. channel) and different bands in config (P1). | Unit: score_band boundaries; integration: score distribution. | Documented; optional segment-aware bands (P1). | `make test`; `pytest tests/test_scoring.py -v` |
| 4 | No SAR timeliness: no alert→disposition→SAR timing metrics | **VERIFIED** | Alert has created_at, updated_at; no computed metric (e.g. hours_to_disposition); reporting and audit do not expose timeliness. | Regulators and MI need time-to-disposition and time-to-SAR. | Add to reporting or MI: for each alert with disposition, (updated_at - created_at); aggregate in audit or report (e.g. sar_timeliness summary). | Integration: PATCH alert disposition, generate report or query; assert timeliness in output or audit. | Timeliness (e.g. hours_to_disposition) available in report or MI. | `make run` then PATCH alert, `aml generate-reports`; inspect report or MI |
| 5 | Entity/network underused: RelationshipEdge exists but rules don't use it; counterparty is a string | **PARTIAL** | RelationshipEdge in models; graph_builder builds edges; network_ring uses ring_signal(RelationshipEdge). Other rules use only Transaction; counterparty is string everywhere. | Most rules ignore network; counterparty not resolved to entity limits entity-level risk. | Document that network is used by NetworkRingIndicator only; P1: add one more rule using edges (e.g. fan-out degree) or entity aggregation. | test_network_ring_integration already; add test for edge count used in rule. | At least one rule (already network_ring) uses RelationshipEdge; documented. | `make test`; `pytest tests/test_integration.py::test_network_ring_indicator_integration -v` |
| 6 | Rules version not code-backed: single RULES_VERSION; no per-rule hash | **VERIFIED** | `__init__.py`: RULES_VERSION = "1.0.0"; Alert has rules_version; no per-rule hash or code fingerprint. | Cannot prove which rule code version produced an alert for a specific rule. | Add per-rule version or hash to rule module (e.g. RULE_HASH from source hash) and store in evidence or audit when rule fires; or document RULES_VERSION = deploy tag. | Unit: rule exports version/hash; integration: alert evidence or audit contains it. | Per-rule version or hash in alert/audit or documented mapping. | `make test`; grep for RULE_HASH or per-rule version |
| 7 | No backpressure/chunking: run_rules loads all transactions; no resume/checkpoint | **VERIFIED** | `run_rules.py` 42–44: `stmt = select(Transaction).order_by(Transaction.id)`; `for txn in session.execute(stmt).scalars().all()` — full load. | Large datasets cause OOM and no resume after failure. | Process in chunks (e.g. LIMIT/OFFSET or id > last_id); write checkpoint (last_processed_id) to audit or table; resume from checkpoint. | Integration: run_rules with 2 chunks; assert both chunks processed and audit has chunk info. | Bounded memory or chunk audit; resume from checkpoint. | `make test`; synthetic 10k run_rules chunked (new test) |
| 8 | Sanctions/list primitive: static keyword list; no version/effective date recorded | **VERIFIED** | sanctions_keyword.py: config keywords list; high_risk_country: config countries. No list version or effective_date in config or Alert. | Cannot prove which list version was in effect at alert time. | Add sanctions_list_version and effective_date to config and persist in Alert evidence or audit when rule fires. | Unit: rule stores list_version in evidence; integration: alert evidence contains it. | List version/effective date in config and in alert evidence. | `make test`; assert evidence or details_json has list_version |
| 9 | High-risk country placeholder: config includes [XX, YY] placeholders | **VERIFIED** | config/default.yaml 44–45: `countries: [XX, YY]` with comment "placeholder". dev.yaml overrides with IR, KP, SY, CU. | Production could ship with placeholder and never flag high-risk country. | Fail or warn at config load if high_risk_country.countries contains XX/YY; or replace with empty and document. | Config load test: default has XX/YY; dev or prod config validation rejects XX/YY. | No placeholder in production config; validation or doc. | `pytest tests/test_config.py -v`; add test_config_rejects_placeholder |
| 10 | API key not scoped: one actor per key; no roles/scopes | **VERIFIED** | auth.py: parse_api_keys_env → name:key; require_api_key returns actor name. No scope or role check on endpoints. | All keys have same privilege; cannot restrict e.g. read-only. | Add optional scopes/roles per key (e.g. in env or config); in require_api_key or dependency, check scope for route (e.g. alerts:write). | API test: key with scope read_only cannot PATCH alert. | At least one scope or role enforced (e.g. write for PATCH). | `pytest tests/test_api.py -v`; add test_scope_denies_patch |

---

## 3) ADDITIONAL HIDDEN WEAKNESSES (RANKED)

| Severity | Tags | Weakness | Evidence | Fix | Tests | Acceptance | Verification |
|----------|------|----------|----------|-----|-------|------------|---------------|
| **Med** | hidden cost | Reject visibility done; no quarantine or replay | csv_ingest/jsonl_ingest now persist rows_rejected + reject_reasons in audit (P0.1 done) | Optional: quarantine table; replay-rejects CLI | test_ingest_rejects | rows_rejected + reject_reasons in audit | pytest test_ingest_rejects |
| **Critical** | fails production | run_rules loads all txns in memory; no chunking | run_rules.py 42–44 select all, iterate | Chunk by id or LIMIT; checkpoint; resume | test_run_rules_chunked | Chunk audit or bounded memory | pytest + 10k synthetic |
| **High** | fails audit | Audit log not tamper-resistant | models.AuditLog; no hash_chain or signature | Append-only + optional hash_chain (prev_id, row_hash) or sign-on-write | test_audit_chain | Hash or signature on audit row | pytest test_audit |
| **High** | false confidence | Reproduce bundle cannot replay without DB | reproduce.py: no transactions array; only transaction_id on alerts | Include transaction rows for alerts in bundle OR document "replay requires same DB" and add export command | test_reproduce_contains_txn_payload_or_doc | Bundle replayable or documented + export | aml reproduce-run; inspect bundle |
| **High** | fails audit | No SAR/alert timeliness metrics | reporting.py, Alert model: no hours_to_disposition | Add timeliness to report or MI (created_at, updated_at, disposition) | test_report_timeliness | Report or MI has timeliness | generate-reports; assert output |
| **Med** | false confidence | No golden-file or determinism test for reports | test_integration does not assert exact alert IDs for same input | Golden file or deterministic seed test: same input → same alert count/ids | test_determinism | Same seed → same alerts | pytest test_determinism |
| **Med** | hidden cost | No suppression or tuning governance for false positives | No suppression list or rule-level FP rate; tuning writes YAML only | Document suppression approach; optional suppression list + test | test_suppression_or_doc | Suppression or tuning governance doc | docs/GOVERNANCE/TUNING.md |
| **Med** | fails production | No health endpoint | api.py has no /health | Add GET /health (DB ping, optional version) | test_health | 200 and body | curl /health |
| **Low** | investigator | No entity history or relationship view in API | API returns transaction/case; no GET entity or network view | P1: GET /entities/{id} or /network/account/{id} with edges | test_entity_or_network_api | Endpoint returns entity/edges | curl /network/account/1 |

---

## 4) ADVERSARIAL & TORTURE TEST HARNESS

### 4.1 Dirty data attacks (ingest integrity)

- **Malformed rows:** Invalid ts, non-numeric amount, missing required (e.g. iban empty), invalid types.
- **Invalid ISO currency:** 2-char or 4-char currency.
- **Timezone drift:** Same instant in different TZ strings; ensure external_id stable.
- **Duplicates:** Same row twice → second insert 0 (idempotent).
- **Negative amounts, extreme values:** amount -1e12, 1e12 (schema allows; business rule may want reject).

**Expected:** Rejects counted and reasons persisted; no silent drop.  
**Dataset generator:** `tests/fixtures/dirty_ingest.csv` (or inline in test): header + valid row + bad_ts row + bad_amount row + empty_iban row + duplicate of valid row.  
**Commands:** `poetry run pytest tests/test_adversarial_ingest.py -v`  
**Pass/fail:** After ingest: rows_inserted = 1 (or 2 if duplicate handled as insert once); audit details_json has rows_rejected >= 1 and reject_reasons list.  
**Where in code:** Implemented in `ingest/csv_ingest.py` and `ingest/jsonl_ingest.py`: rows_rejected, reject_reasons (cap 500), details_json when rows_rejected > 0.

### 4.2 Evasion patterns (rule defeat)

- **Structuring just under threshold:** e.g. 3 x 9k in 60 min (structuring_smurfing threshold 9500, min 3). Expect alert or document out-of-scope.
- **Smurfing:** Many small txns across counterparties in short window; rapid_velocity is per-account count (no cross-counterparty). Expect rapid_velocity if same account.
- **Mule networks:** Multiple accounts sharing counterparties (network_ring). Already covered by test_network_ring_indicator_integration.
- **Round-tripping:** A→B→A; no dedicated rule; document if out-of-scope.
- **Name variation:** Sanctions keyword "sanctioned" vs "sancioned"; current rule is substring — typo may evade. Add test with typo; expect no match or add fuzzy (P2).

**Expected:** At least one scenario catches each pattern OR scenario library marks OUT-OF-SCOPE.  
**Dataset:** tests/fixtures/evasion_*.csv or generate in test (e.g. structuring_just_under.csv).  
**Commands:** `poetry run pytest tests/test_adversarial_evasion.py -v`  
**Pass/fail:** Structuring: alert StructuringSmurfing or doc; smurfing: RapidVelocity or doc; ring: NetworkRingIndicator; round-trip: doc.  
**Where:** tests/test_adversarial_evasion.py; optionally docs/scenario_library.md with scenario_id and expected rule or OUT_OF_SCOPE.

### 4.3 False positive traps (noise realism)

- **Payroll batches, rent, bills, merchant aggregation, tuition:** No suppression logic in code. Either add suppression (e.g. merchant/counterparty allowlist) or document tuning + governance.

**Expected:** Suppression logic exists or tuning hooks + governance documented and testable.  
**Dataset:** Fixture with payroll-like batch (same amount, same counterparty, periodic).  
**Commands:** `poetry run pytest tests/test_adversarial_fp.py -v`  
**Pass/fail:** Either alert suppressed or alert created and governance doc states how to tune.  
**Where:** docs/GOVERNANCE/TUNING.md; optional suppression in config + rule or post-filter.

### 4.4 Scale/backpressure

- **10k / 100k / 1M transactions:** generate_synthetic_data.py extended with size param or separate script.

**Expected:** Bounded memory, chunked processing, checkpoint + resume, chunk audit records.  
**Commands:** `python scripts/generate_synthetic_data.py --rows 10000`; `aml run-rules` with chunking; monitor memory; assert audit has chunk/chunk_size or last_id.  
**Pass/fail:** No OOM; chunk audit present; resume from checkpoint produces same total alerts.  
**Where:** run_rules.py: loop in chunks; persist last_processed_id; resume from it.

### 4.5 Determinism & evidence invariants

- **Same input twice:** Same CSV, same config, same seed → same alert count and same alert rule_id per transaction (and optionally same alert ids if DB reset).

**Expected:** Identical alerts/cases/reports OR controlled, explained variance; reproduce bundle replays exactly (with same DB or with transactions in bundle).  
**Dataset:** tests/fixtures/determinism.csv (fixed); seed 42 for synthetic.  
**Commands:** `poetry run pytest tests/test_determinism.py -v` (two runs, same ingest, compare alert counts and rule_ids).  
**Pass/fail:** Run 1 and Run 2: same number of alerts; same set of (transaction_id, rule_id).  
**Where:** test_determinism.py; optionally reproduce.py include transaction payloads for alerts.

---

## 5) 2026 TARGET STATE (THIS PROJECT ONLY)

### Target architecture

- **Components:** Ingest service (CSV/JSONL → validate → reject log + insert); Rule engine (chunked run_rules + checkpoint); Network builder (chunked); API (auth with scopes); Reporter (SAR + timeliness); Reproduce (bundle with optional transaction snapshot). Same repo, optional split into ingest/engine/api later.
- **Boundaries:** Config-driven rules; versioned lists (sanctions, high-risk country) with effective_date; per-rule version/hash in alert evidence; audit with hash chain or signature.

### Required artifacts ("Audit Pack")

| Artifact | Content |
|----------|--------|
| system_overview.md | Architecture, dataflow, components (already ARCHITECTURE.md; extend with error handling and MI). |
| data_contract.md | Transaction, Alert, Case, Report schemas; required fields; validation rules; reject reasons. |
| scenario_library.md | Typology id, description, expected rule or OUT_OF_SCOPE, test fixture reference. |
| rule_register.csv | rule_id, scenario_id, severity, params, owner, last_tested, version/hash. |
| tuning_history.md | Date, rule_id, params_before, params_after, effectiveness snapshot (optional). |
| testing_and_effectiveness.md | Test coverage; deterministic run; adversarial tests; effectiveness proxies. |
| change_management.md | How config and code changes are approved, deployed, and audited. |
| security_and_privacy.md | Authn/authz, scopes, secrets, PII handling, retention, audit integrity. |

### Operating metrics (MI)

- **Data quality:** rows_rejected by reason, null rate for key fields, duplicate rate (inserted vs read).
- **Detection:** Alerts per rule, alert rate per 1k txns, severity distribution.
- **Workflow:** Time-to-triage, time-to-close, backlog, reopen rate (if status transitions tracked).
- **Effectiveness proxies:** Escalation rate, SAR-ready rate, analyst override (false_positive) rate.
- **Stability:** Runtime, memory, error rate (from logs or health).
- **Governance:** Rule changes per month, tuning events, approvals (from change_management).

### Procurement-ready UX (minimum)

- **API:** GET /alerts (filter by correlation_id, severity, status, date range); PATCH /alerts/{id} (status, disposition); GET /cases, POST/PATCH /cases; GET /transactions/{id}; GET /health; optional GET /network/account/{id}.
- **CLI:** Same as today; add `aml export-rejects` or reject file path in ingest output.
- **UI (dashboard):** List alerts with filters; case list; link to report and reproduce bundle. Document in DASHBOARD.md.

---

## 6) REMEDIATION PLAN (P0/P1/P2)

### P0 — Credibility + audit survival + no silent loss

| Step | Goal | Exact repo changes | Acceptance criteria | Tests to add | Verification | Effort |
|------|------|--------------------|---------------------|--------------|--------------|--------|
| P0.1 | Ingest reject visibility | **DONE.** csv_ingest.py, jsonl_ingest.py: rows_rejected, reject_reasons (missing_iban, parse_error:Type) in audit details_json when rejects > 0 | details_json has rows_rejected, reject_reasons | test_ingest_rejects.py | `make test-ingest-rejects` | Small |
| P0.2 | Config placeholder validation | config.py or validation: warn/fail if high_risk_country.countries contains XX or YY | Load with XX/YY fails or warns | test_config_placeholder | `pytest tests/test_config.py` | Small |
| P0.3 | Run_rules chunking + checkpoint | run_rules.py: process in chunks (e.g. 5000 by id); write last_processed_id and chunk index to run_rules audit details | details_json has chunk info; resume possible | test_run_rules_chunked | `pytest tests/test_run_rules.py` (new) | Medium |
| P0.4 | SAR timeliness in report or MI | reporting.py or new MI export: add alert created_at, updated_at, hours_to_disposition (if disposition set) to JSON or separate summary | Report or MI has timeliness fields | test_report_timeliness | `aml generate-reports`; assert JSON | Small |
| P0.5 | Health endpoint | api.py: GET /health returning 200, optional db ping and version | 200; body with status | test_api.py test_health | `curl http://localhost:8000/health` | Small |

### P1 — Operational effectiveness + tuning evidence + investigator utility

| Step | Goal | Exact repo changes | Acceptance criteria | Tests to add | Verification | Effort |
|------|------|--------------------|---------------------|--------------|--------------|--------|
| P1.1 | Rule register / tuning history | docs/rule_register.csv or tuning_history.md; updated by train or manually; reference in TUNING.md | Artifact exists; doc updated | Optional test that file exists after train | `aml train`; check docs | Small |
| P1.2 | Per-rule version or hash | Each rule module exports RULE_VERSION or RULE_HASH; store in Alert.evidence_fields or audit when rule fires | Alert or audit has per-rule version | test_alert_has_rule_version | `pytest tests/test_rules.py` | Small |
| P1.3 | Sanctions/list version in evidence | sanctions_keyword, high_risk_country: add list_version and effective_date from config; store in evidence_fields | evidence has list_version/effective_date | test_evidence_has_list_version | `pytest tests/test_rules.py` | Small |
| P1.4 | Reproduce bundle with transaction payloads | reproduce.py: for each alert, include transaction row (or snapshot) in bundle | Bundle has transactions for alert transaction_ids | test_reproduce_has_transactions | `aml reproduce-run <cid>`; assert bundle | Medium |
| P1.5 | API scopes/roles | auth.py: optional scope per key; require scope for PATCH /alerts, POST /cases | Key without scope cannot mutate | test_api_scope_deny | `pytest tests/test_api.py` | Medium |
| P1.6 | GET /network/account/{id} or entity view | api.py: endpoint returning edges for account (or entity) | 200; edges in response | test_network_endpoint | `curl /network/account/1` | Small |

### P2 — Differentiators

| Step | Goal | Exact repo changes | Acceptance criteria | Tests to add | Verification | Effort |
|------|------|--------------------|---------------------|--------------|--------------|--------|
| P2.1 | Audit log hash chain | AuditLog row: prev_id, row_hash (hash of prev_hash + this row); or sign-on-write | Tamper detection possible | test_audit_chain | Verify chain | Large |
| P2.2 | Segment-aware scoring | scoring.py + config: band thresholds per segment (e.g. channel or customer_type) | Different bands per segment | test_scoring_segment | `pytest tests/test_scoring.py` | Medium |
| P2.3 | Scenario library + adversarial tests | docs/scenario_library.md; tests/test_adversarial_*.py (ingest, evasion, FP, scale, determinism) | All scenarios have expected outcome | test_adversarial_* | `pytest tests/test_adversarial_*` | Large |
| P2.4 | Suppression or FP governance | Config or code: suppression list; or doc tuning governance + FP rate tracking | Suppression works or doc | test_suppression | docs + optional test | Medium |
| P2.5 | Optional ML with governance | Placeholder: model version, input/output schema, approval in change_management | Documented; no silent ML | Doc only or stub | N/A | Medium |

---

## 7) KILLER DIFFERENTIATORS — 5 features for 2026 sell

1. **Data quality visibility (P0.1)** — Reject counts and reasons in ingest audit; no silent loss. **Repo:** csv_ingest.py, jsonl_ingest.py, audit details_json; test_ingest_rejects. **Buyer message:** "Every row is accounted for; examiners see exactly what was rejected and why."

2. **Chunked, resumable rule engine (P0.3)** — Bounded memory and checkpoint/resume for run_rules. **Repo:** run_rules.py chunks + checkpoint in audit. **Buyer message:** "Scale to millions of transactions without OOM; resume after failure."

3. **SAR timeliness and audit trail (P0.4 + existing correlation_id/version)** — Timeliness in report/MI; alert→disposition traceability with config_hash and rules_version. **Repo:** reporting.py or MI; existing Alert timestamps. **Buyer message:** "Prove time-to-disposition and which rule version produced each alert."

4. **Reproduce bundle with transaction snapshot (P1.4)** — Bundle includes transaction payloads for alerts so replay is possible without DB. **Repo:** reproduce.py. **Buyer message:** "Full reproducibility: hand a bundle to audit and they can re-run the same inputs."

5. **Scenario library and adversarial tests (P2.3)** — Documented typologies, expected rules, and tests that try to defeat the engine. **Repo:** docs/scenario_library.md, test_adversarial_*.py. **Buyer message:** "We test against real evasion patterns and document what we catch and what we don’t."

---

*End of THREAD C+D deliverable.*
