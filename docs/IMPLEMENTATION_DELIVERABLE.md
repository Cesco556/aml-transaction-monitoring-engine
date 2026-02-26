# Implementation Deliverable — ENGINE IMPLEMENTER + AUDITOR

## 1) CHANGELOG

### P0.2 Config placeholder validation (XX/YY)
- **config.py** — Added `HIGH_RISK_COUNTRY_PLACEHOLDERS`, `validate_high_risk_country()`, call from `get_config()`.
- **tests/test_config.py** — Added `test_config_rejects_placeholder_xx_yy`, `test_config_allows_valid_high_risk_countries`, `test_validate_high_risk_country_skips_when_disabled`.
- **tests/conftest.py** — Changed high_risk_country countries from `[IR, XX]` to `[IR, KP]`.

### P0.3 Chunked + resumable run_rules
- **config/default.yaml** — Added `run_rules.chunk_size: 0`.
- **run_rules.py** — Rewritten: chunk loop by `Transaction.id` when chunk_size > 0; `_get_last_processed_id()`; `resume_from_correlation_id`; checkpoint `last_processed_id`, `chunk_index` in AuditLog details_json.
- **cli.py** — run_rules_cmd: added `--resume`, `--correlation-id`; pass `resume_from_correlation_id` to run_rules.
- **tests/test_run_rules.py** — New: `test_chunk_sizes_produce_identical_alerts`, `test_resume_no_duplicates_no_skips`.

### P0.4 SAR timeliness in reporting
- **reporting.py** — Select Alert.created_at, Alert.updated_at; records include created_at, updated_at, hours_to_disposition; CSV fieldnames extended.
- **tests/test_integration.py** — Added `test_sar_report_includes_timeliness_and_hours_to_disposition`.

### P0.5 /health endpoint
- **api.py** — Added GET /health; returns status, engine_version, rules_version, db_status (ping via get_engine).
- **tests/test_api.py** — Added `test_health_returns_200_and_version`.

### P1.4 Reproduce bundle: transactions + resolved config
- **reproduce.py** — Added `_transaction_to_dict()`; bundle["transactions"] for all transaction_ids from alerts; bundle["config"]["resolved"] = get_config(config_path).
- **tests/test_integration.py** — Extended `test_reproduce_run_produces_bundle_and_audit_log`: assert transactions[], alert transaction_id in transactions, required keys, config.resolved.

### P1.2 Per-rule version/hash on alerts
- **rules/base.py** — Added `stable_rule_hash()`, `RULE_HASH`, `get_rule_hash()`.
- **run_rules.py** — When creating Alert, merge evidence_fields with rule_hash from rule.get_rule_hash().
- **tests/test_integration.py** — Added `test_alerts_include_per_rule_hash_in_evidence`.

### P1.3 Lists discipline: list_version + effective_date
- **config/default.yaml** — sanctions_keyword and high_risk_country: list_version "1.0", effective_date "2026-01-01".
- **rules/sanctions_keyword.py** — Read list_version, effective_date; add to evidence_fields when rule fires.
- **rules/high_risk_country.py** — Same.
- **tests/test_rules.py** — Added `test_sanctions_evidence_has_list_version_and_effective_date`, `test_high_risk_country_evidence_has_list_version_and_effective_date`.

### P1.5 API key scopes/roles
- **auth.py** — parse_api_keys_env returns (name_to_key, key_to_scope); format name:key:scope; require_api_key sets _current_scope; require_write_scope(), require_api_key_write().
- **api.py** — PATCH /alerts uses require_api_key_write.
- **cases_api.py** — POST /cases, PATCH /cases/{id}, POST /cases/{id}/notes use require_api_key_write.
- **tests/test_api.py** — Added `test_read_only_key_gets_403_on_patch_alerts`, `test_write_key_succeeds_patch_alerts`.

### P1.6 GET /network/account/{id}
- **api.py** — Added GET /network/account/{account_id}; returns edges list and ring_signal (overlap_count, linked_accounts, shared_counterparties, degree).
- **tests/test_api.py** — Added `test_network_account_returns_edges`.

### P2.1 Audit log hash chain
- **models.py** — AuditLog: added prev_hash, row_hash (String(64) nullable).
- **db.py** — _SCHEMA_COLUMNS audit_logs: prev_hash, row_hash; _audit_row_canonical(), _compute_audit_chain(); before_flush event calls _compute_audit_chain(session).
- **alembic/versions/a1b2c3d4e5f6_audit_log_hash_chain.py** — New migration adding prev_hash, row_hash.
- **tests/test_audit_chain.py** — New: test_audit_log_has_prev_hash_and_row_hash, test_audit_chain_verification, test_tampering_breaks_verification.

### P2.3 Scenario library + adversarial + determinism
- **docs/scenario_library.md** — New: typology table (scenario_id, description, expected_rule or OUT_OF_SCOPE); adversarial/determinism notes.
- **tests/test_adversarial_evasion.py** — New: test_evasion_structuring_just_under_triggers_rule, test_evasion_smurfing_velocity_triggers_rule.
- **tests/test_determinism.py** — New: test_same_input_twice_same_alert_set, test_chunk_size_invariance_already_in_run_rules (skip).
- **Makefile** — test-adversarial, test-determinism, test-scenario targets.

### Planning
- **docs/IMPLEMENTATION_CHANGELOG_PLAN.md** — Pre-implementation plan (file list).

---

## 2) PATCH SUMMARY PER ITEM

| Item | What was implemented | Where | Tests added | Acceptance criteria | Verification commands |
|------|----------------------|--------|-------------|---------------------|------------------------|
| P0.2 | Config validation raises ValueError if high_risk_country.countries contains XX or YY; validate_high_risk_country() called at end of get_config(). | config.py (validate_high_risk_country, get_config) | test_config.py (test_config_rejects_placeholder_xx_yy, test_config_allows_valid_high_risk_countries, test_validate_high_risk_country_skips_when_disabled) | Invalid config raises; valid passes; disabled skips validation | `pytest tests/test_config.py -v` |
| P0.3 | Chunking by Transaction.id with config run_rules.chunk_size; last_processed_id and chunk_index in AuditLog details; resume_from_correlation_id reads last_processed_id and continues. | run_rules.py, config/default.yaml, cli.py | test_run_rules.py (test_chunk_sizes_produce_identical_alerts, test_resume_no_duplicates_no_skips) | Same alerts for chunk_size 0 vs 2; resume does not duplicate | `pytest tests/test_run_rules.py -v` |
| P0.4 | SAR report JSON/CSV include created_at, updated_at, hours_to_disposition per alert. | reporting.py (select, records, fieldnames) | test_integration.py (test_sar_report_includes_timeliness_and_hours_to_disposition) | Report has timeliness; hours_to_disposition ≈ 2.0 for 2h delta | `pytest tests/test_integration.py -k timeliness -v` |
| P0.5 | GET /health returns 200, status, engine_version, rules_version, db_status (SELECT 1). | api.py (health()) | test_api.py (test_health_returns_200_and_version) | 200; body has status, engine_version, rules_version, db_status | `pytest tests/test_api.py -k health -v` |
| P1.4 | Bundle includes transactions[] (all txns referenced by alerts) and config.resolved (full merged config). | reproduce.py (_transaction_to_dict, bundle transactions, config.resolved) | test_integration.py (extended test_reproduce_run_produces_bundle_and_audit_log) | Bundle has transactions; every alert.transaction_id in transactions; config.resolved present | `pytest tests/test_integration.py -k reproduce -v` |
| P1.2 | Per-rule hash in alert evidence_fields via rule.get_rule_hash() (stable_rule_hash(rule_id) or RULE_HASH). | rules/base.py, run_rules.py (ev["rule_hash"] = rule.get_rule_hash()) | test_integration.py (test_alerts_include_per_rule_hash_in_evidence) | Every alert with evidence has rule_hash non-empty string | `pytest tests/test_integration.py -k per_rule_hash -v` |
| P1.3 | sanctions_keyword and high_risk_country config: list_version, effective_date; stored in evidence_fields when rule fires. | config/default.yaml, sanctions_keyword.py, high_risk_country.py | test_rules.py (test_sanctions_evidence_has_list_version_and_effective_date, test_high_risk_country_evidence_has_list_version_and_effective_date) | Evidence has list_version and effective_date | `pytest tests/test_rules.py -k list_version -v` |
| P1.5 | API keys support optional :scope (read_only | read_write); require_api_key_write used for PATCH /alerts, POST/PATCH /cases, POST /cases/{id}/notes; read_only → 403. | auth.py (parse_api_keys_env, require_write_scope, require_api_key_write), api.py, cases_api.py | test_api.py (test_read_only_key_gets_403_on_patch_alerts, test_write_key_succeeds_patch_alerts) | read_only key gets 403 on PATCH; write key succeeds | `pytest tests/test_api.py -k "read_only or write_key" -v` |
| P1.6 | GET /network/account/{account_id} returns edges and ring_signal (overlap_count, linked_accounts, shared_counterparties, degree). | api.py (get_network_account) | test_api.py (test_network_account_returns_edges) | 200; body has account_id, edges, edge_count, ring_signal | `pytest tests/test_api.py -k network_account -v` |
| P2.1 | AuditLog prev_hash, row_hash; before_flush computes row_hash = SHA256(prev_hash + canonical(row)); chain verification. | models.py (prev_hash, row_hash), db.py (_audit_row_canonical, _compute_audit_chain, before_flush), alembic migration | test_audit_chain.py (test_audit_log_has_prev_hash_and_row_hash, test_audit_chain_verification, test_tampering_breaks_verification) | New rows have row_hash; second row prev_hash == first row_hash; tampering leaves stale row_hash | `AML_ALLOW_SCHEMA_UPGRADE=true pytest tests/test_audit_chain.py -v` |
| P2.3 | scenario_library.md; adversarial tests (structuring, smurfing); determinism test (same input → same alert set); Makefile targets. | docs/scenario_library.md, tests/test_adversarial_evasion.py, tests/test_determinism.py, Makefile | test_adversarial_evasion.py, test_determinism.py | Structuring/Smurfing scenarios fire expected rule; same CSV twice → same (ext_id, rule_id) set | `make test-adversarial`, `make test-determinism`, `make test-scenario` |

---

## 3) UPDATED DOCS CONFIRMATION

### docs/THREAD_CD_FULL_AUDIT_AND_2026_PLAN.md
- **Section 0 REPO EVIDENCE INDEX:** Updated rows for run_rules.py (chunking, checkpoint, rule_hash), config.py (validate_high_risk_country), auth.py (scopes), api.py (/network/account, /health), reporting.py (timeliness), reproduce.py (transactions, config.resolved), models.py (AuditLog prev_hash, row_hash), rules base/sanctions/high_risk (list_version, effective_date, RULE_HASH), cli.py (--resume, --correlation-id). Added entries for docs/scenario_library.md, tests/test_run_rules.py, test_audit_chain.py, test_adversarial_evasion.py, test_determinism.py, alembic a1b2c3d4e5f6.

### docs/THREAD_CD_DOC_REVIEW_AND_BLOCKERS.md
- **Section E) IMPLEMENTATION STATUS (POST-P0–P2):** Added. Table marking A.2, A.3, B2.1, B2.3, B2.4, B3, B4.1, B5.1–B5.3, B6.1–B6.2, B7.1–B7.2, B8.2, and C.1–C.10 as **FIXED** with evidence paths and test names. Note on still-missing items and pointer to IMPLEMENTATION_DELIVERABLE.
- No structural change in this pass; document remains the review against code. Blockers C) and D) are partially addressed by this implementation (reproduce replay, timeliness, chunking, /health, list versioning, per-rule hash, scopes, network endpoint, audit chain, scenario/adversarial/determinism tests). A follow-up edit can set “FIXED” for each implemented blocker.

### docs/scenario_library.md
- **Created.** Typology table (scenario_id, description, expected_rule, notes); adversarial and determinism coverage notes.

---

## 4) FINAL RE-RUN THREAD C+D REVIEW

### What is FIXED (with evidence pointers)

| Item | Evidence |
|------|----------|
| Config placeholder XX/YY | config.py: validate_high_risk_country(); get_config() calls it; raises ValueError. test_config.py. |
| run_rules chunking + checkpoint + resume | run_rules.py: chunk_size, last_processed_id in details_json, resume_from_correlation_id; cli --resume --correlation-id. test_run_rules.py. |
| SAR timeliness in report | reporting.py: created_at, updated_at, hours_to_disposition in records and CSV. test_sar_report_includes_timeliness_and_hours_to_disposition. |
| /health endpoint | api.py: GET /health; engine_version, rules_version, db_status. test_health_returns_200_and_version. |
| Reproduce bundle self-contained | reproduce.py: bundle["transactions"], bundle["config"]["resolved"]. test_integration test_reproduce_run asserts transactions and config.resolved. |
| Per-rule hash on alerts | rules/base.py get_rule_hash(); run_rules.py evidence_fields["rule_hash"]. test_alerts_include_per_rule_hash_in_evidence. |
| List version/effective_date in evidence | sanctions_keyword.py, high_risk_country.py: list_version, effective_date in config and evidence_fields. test_rules.py. |
| API key scopes (read vs write) | auth.py: require_api_key_write; PATCH /alerts, POST/PATCH cases use it. test_read_only_key_gets_403_on_patch_alerts. |
| GET /network/account/{id} | api.py: get_network_account(); edges + ring_signal. test_network_account_returns_edges. |
| Audit log tamper resistance | models.AuditLog prev_hash, row_hash; db._compute_audit_chain, before_flush. test_audit_chain.py. |
| Scenario library + adversarial + determinism | docs/scenario_library.md; test_adversarial_evasion.py; test_determinism.py; Makefile test-adversarial, test-determinism, test-scenario. |

### What is still MISSING/BLOCKING procurement (ranked top 10)

1. **RULES_VERSION not tied to git/build** — Still hardcoded in __init__.py. Evidence: src/aml_monitoring/__init__.py. Fix: Set from env BUILD_SHA or git describe at package build.
2. **rule_register.csv / tuning effectiveness metrics** — No rule_register.csv; tuning.py only outputs thresholds, no precision/recall. Evidence: no docs/rule_register.csv; tuning.py. Fix: Add rule_register.csv and optional effectiveness snapshot on train.
3. **Reject replay / quarantine** — Rejects only in audit; no quarantine table or replay command. Evidence: ingest only writes to AuditLog. Fix: Optional quarantine table or reject file + CLI replay.
4. **ISO currency validation at ingest** — Currency is truncated to 3 chars, no ISO 4217 check. Evidence: csv_ingest.py, jsonl_ingest.py. Fix: Validate against allowed list or document out-of-scope.
5. **Determinism test uses external_id** — test_same_input_twice_same_alert_set compares (external_id, rule_id); external_id is stable but run_rules does not set Transaction.external_id (ingest does). Evidence: test_determinism.py. Acceptable if ingest sets external_id and run uses same DB.
6. **PII redaction** — No redaction in reports/logs. Evidence: reporting.py, logs. Fix: Document or add redaction for PII fields in export.
7. **Separate read-only keys** — Keys can have read_only scope (403 on write) but GET /alerts and GET /transactions are unauthenticated. Evidence: api.py. Fix: Optional auth on GET and scope read for read_only keys.
8. **Full replay from bundle without DB** — Bundle has transactions and config.resolved; no loader that re-ingests from bundle and re-runs rules. Evidence: reproduce.py. Fix: CLI or script that loads bundle JSON and replays (ingest transactions, run_rules) for audit.
9. **SLA/backlog metrics** — No backlog count or SLA. Evidence: no MI endpoint. Fix: Optional MI endpoint or report with backlog and time-to-close aggregates.
10. **Alembic migration for SQLite** — SQLite uses _upgrade_schema for prev_hash/row_hash; Alembic migration exists for Postgres. Evidence: db.py _SCHEMA_COLUMNS, alembic a1b2c3d4e5f6. No blocker if AML_ALLOW_SCHEMA_UPGRADE used for SQLite.

### Proof checklist results (pass/fail)

| Check | Result | Evidence |
|-------|--------|----------|
| Determinism (same input twice → same alerts) | PASS | test_same_input_twice_same_alert_set |
| Chunk invariants (chunk_size change → same outputs) | PASS | test_chunk_sizes_produce_identical_alerts |
| Resume invariants (no duplicate/skip) | PASS | test_resume_no_duplicates_no_skips |
| Reproduce replay (bundle has txns + config) | PASS | test_reproduce_run asserts transactions[], config.resolved |
| Timeliness in report | PASS | test_sar_report_includes_timeliness_and_hours_to_disposition |
| Scopes (read_only 403 on mutation) | PASS | test_read_only_key_gets_403_on_patch_alerts |
| /health | PASS | test_health_returns_200_and_version |
| List versioning in evidence | PASS | test_sanctions_evidence_has_list_version_and_effective_date, test_high_risk_country_evidence_has_list_version_and_effective_date |
| Per-rule hash in alert | PASS | test_alerts_include_per_rule_hash_in_evidence |
| Scenario/adversarial tests | PASS | test_evasion_structuring_just_under_triggers_rule, test_evasion_smurfing_velocity_triggers_rule; docs/scenario_library.md |

### Single next best patch

**Tie RULES_VERSION to build/git (or env).**  
- **Goal:** Procurement can prove which code version produced alerts.  
- **Changes:** In `src/aml_monitoring/__init__.py`, set `RULES_VERSION = os.environ.get("AML_RULES_VERSION") or _git_version() or "1.0.0"` with `_git_version()` returning `subprocess.check_output(["git", "describe", "--always"], text=True).strip()` when .git exists, else None. Or set in Docker/build from BUILD_SHA.  
- **Tests:** Assert env AML_RULES_VERSION is used when set.  
- **Verification:** `AML_RULES_VERSION=2.0.0 python -c "from aml_monitoring import RULES_VERSION; assert RULES_VERSION == '2.0.0'"`
