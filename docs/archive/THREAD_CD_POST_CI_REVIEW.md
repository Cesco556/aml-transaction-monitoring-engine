---
**HISTORICAL (pre-P0–P2 implementation). Current state: see docs/IMPLEMENTATION_DELIVERABLE.md and docs/DOCS_CONSISTENCY_AUDIT.md.**

---
# THREAD C+D POST-CI REVIEW (strict output)

**Context:** CI green (`./scripts/ci.sh` exit 0). Review against current repo state.

---

## 1) WHAT IS FIXED (with repo evidence)

- **Config placeholder XX/YY validation** → `src/aml_monitoring/config.py`: `validate_high_risk_country()`, `HIGH_RISK_COUNTRY_PLACEHOLDERS`; called in `get_config()` (lines 72, 89). Raises `ValueError` if countries contain XX or YY.
- **Chunked + resumable run_rules** → `src/aml_monitoring/run_rules.py`: `_get_last_processed_id()`, `chunk_size` from config, loop by `Transaction.id > last_processed_id` with `limit(chunk_size)`, `last_processed_id`/`chunk_index` in AuditLog `details_json`; `resume_from_correlation_id`; `cli.py`: `--resume`, `--correlation-id`.
- **SAR timeliness in reporting** → `src/aml_monitoring/reporting.py`: select `Alert.created_at`, `Alert.updated_at`; records include `created_at`, `updated_at`, `hours_to_disposition`; CSV fieldnames include them (lines 49–50, 64–79, 88–96, 119–121).
- **GET /health** → `src/aml_monitoring/api.py`: `@app.get("/health")` (line 139); returns status, engine_version, rules_version, db_status.
- **Reproduce bundle: transactions[] + config.resolved** → `src/aml_monitoring/reproduce.py`: `bundle["transactions"]`, `_transaction_to_dict()`; `bundle["config"]["resolved"] = get_config(...)` (lines 155, 159, 202, 242–243).
- **Per-rule hash on alerts** → `src/aml_monitoring/rules/base.py`: `stable_rule_hash()`, `RULE_HASH`, `get_rule_hash()`; `run_rules.py` line 111: `ev["rule_hash"] = rule.get_rule_hash()`.
- **List version/effective_date in evidence** → `src/aml_monitoring/rules/sanctions_keyword.py`: `list_version`, `effective_date` from config, added to evidence (14–15, 26–27); `high_risk_country.py` (14–15, 24–25). `config/default.yaml`: list_version "1.0", effective_date "2026-01-01" for both.
- **API key scopes (read_only vs read_write)** → `src/aml_monitoring/auth.py`: `parse_api_keys_env()` returns `key_to_scope`; `require_write_scope()`, `require_api_key_write()`; `api.py` PATCH /alerts uses `require_api_key_write`; `cases_api.py` POST/PATCH cases and notes use it.
- **GET /network/account/{id}** → `src/aml_monitoring/api.py`: `@app.get("/network/account/{account_id}")` (line 93); returns edges, edge_count, ring_signal.
- **Audit log hash chain** → `src/aml_monitoring/models.py`: `AuditLog.prev_hash`, `row_hash`; `db.py`: `_audit_row_canonical()`, `_compute_audit_chain()`, before_flush event (51–52, 77, 83–97, 146).
- **RULES_VERSION from env/git** → `src/aml_monitoring/__init__.py`: `RULES_VERSION = os.environ.get("AML_RULES_VERSION") or _git_version() or "1.0.0"`; `_git_version()` runs `git describe --always --dirty`.
- **Scenario library + adversarial/determinism tests** → `docs/scenario_library.md` (typology table, adversarial/determinism notes); `tests/test_adversarial_evasion.py`, `tests/test_determinism.py`; Makefile targets test-adversarial, test-determinism, test-scenario.

---

## 2) WHAT IS STILL MISSING/BLOCKING PROCUREMENT (TOP 10)

| # | Blocker | Severity | Tags | Evidence | Smallest fix | Tests | Acceptance criteria |
|---|---------|----------|------|----------|--------------|-------|----------------------|
| 1 | **rule_register.csv missing** | High | fails audit | No `docs/rule_register.csv`; THREAD_CD_DOC_REVIEW lists it | Add `docs/rule_register.csv`: columns rule_id, scenario_id, severity, params_snapshot, owner, last_tested, version. One row per rule. | CI or script validates file exists and has required columns | File present; columns rule_id, scenario_id, severity; at least one row per enabled rule |
| 2 | **No reject replay / quarantine** | Med | fails production, hidden cost | Ingest only writes reject count/reasons to AuditLog; no quarantine table or CLI replay | Optional: add `quarantine` table (raw_row, reason, ingest_run_id) or persist reject rows to file; CLI `aml replay-rejects --run-id X` | Test: reject N rows, replay after fix, assert N inserted | Rejects can be re-ingested after schema/parse fix without original file |
| 3 | **ISO currency not validated at ingest** | Med | false confidence | `csv_ingest.py` line 101: `currency = (row.get("currency") or "USD").strip()[:3]`; any 3-char accepted | Validate against allowed set (e.g. ISO 4217 subset) or document "out of scope" in RULE.md | Test: reject or warn on invalid currency code | Documented behavior: accept list or reject invalid |
| 4 | **ENGINE_VERSION hardcoded** | Low | fails audit | `__init__.py`: `ENGINE_VERSION = "0.1.0"` | Set from env `AML_ENGINE_VERSION` or build/git (same pattern as RULES_VERSION) | Test: env override used when set | /health and alerts carry traceable engine version |
| 5 | **No PII redaction in reports/logs** | Med | fails audit | `reporting.py` exports counterparty, account_id, etc. without redaction | Document in RULE.md or add optional redaction (e.g. mask counterparty in CSV export) | N/A or test: redaction flag masks PII fields | Documented or implemented for export |
| 6 | **GET /alerts and GET /transactions unauthenticated** | Low | fails production | `api.py`: list_alerts, get_transaction have no Depends(require_api_key) | Optional: require_api_key on GET; scope "read" for read_only keys | Test: unauthenticated GET 401 when auth enforced | Read access controllable when enabled |
| 7 | **No full replay-from-bundle without DB** | Med | fails audit | Bundle has transactions + config.resolved but no CLI to load bundle JSON and re-run rules | Add `aml replay-bundle bundle.json` (load transactions into temp DB, run_rules with bundle config) | Test: bundle from reproduce_run, replay-bundle produces same alert count | Single command replays run from bundle file |
| 8 | **No SLA/backlog metrics** | Low | hidden cost | No MI endpoint or report with backlog count, time-to-close | Add GET /mi/backlog or extend report with alert age / count by status | Test: backlog count returned or in report | Measurable backlog and/or SLA metric |
| 9 | **default.yaml still contains XX, YY** | Low | false confidence | `config/default.yaml` lines 48–50: countries: [XX, YY]; get_config(default) raises | Intentional: forces override. Document in README that dev config must override countries. | Already tested: test_config_rejects_placeholder_xx_yy | No change needed if documented |
| 10 | **Tuning effectiveness not in rule_register** | Low | false confidence | `tuning.py` only outputs thresholds; no precision/recall per rule | Optional: add effectiveness snapshot (e.g. last run FP count) to rule_register or separate artifact | Test: train writes rule_register row or effectiveness file | Per-rule effectiveness traceable |

---

## 3) PROOF CHECKLIST RESULTS (PASS/FAIL)

| Check | Result | Evidence (test file / symbol) |
|-------|--------|-------------------------------|
| Determinism (same input twice → same alerts) | **PASS** | `tests/test_determinism.py::test_same_input_twice_same_alert_set` |
| Chunk invariants (chunk_size → same outputs) | **PASS** | `tests/test_run_rules.py::test_chunk_sizes_produce_identical_alerts` |
| Resume invariants (no duplicate/skip) | **PASS** | `tests/test_run_rules.py::test_resume_no_duplicates_no_skips` |
| Reproduce replay (transactions[] + config.resolved) | **PASS** | `tests/test_integration.py::test_reproduce_run_produces_bundle_and_audit_log` (asserts bundle has transactions, config.resolved) |
| Timeliness metrics in reporting | **PASS** | `tests/test_integration.py::test_sar_report_includes_timeliness_and_hours_to_disposition` |
| Scopes/roles enforcement | **PASS** | `tests/test_api.py::test_read_only_key_gets_403_on_patch_alerts`, `test_write_key_succeeds_patch_alerts` |
| /health | **PASS** | `tests/test_api.py::test_health_returns_200_and_version` |
| list_version/effective_date in alert evidence | **PASS** | `tests/test_rules.py::test_sanctions_evidence_has_list_version_and_effective_date`, `test_high_risk_country_evidence_has_list_version_and_effective_date` |
| Per-rule hash in alert evidence | **PASS** | `tests/test_integration.py::test_alerts_include_per_rule_hash_in_evidence` |
| Scenario library + adversarial tests | **PASS** | `docs/scenario_library.md`; `tests/test_adversarial_evasion.py::test_evasion_structuring_just_under_triggers_rule`, `test_evasion_smurfing_velocity_triggers_rule` |

---

## 4) SINGLE NEXT BEST PATCH (ONE)

**Choice:** Add **docs/rule_register.csv** and a minimal CI check so the audit pack is complete and rule governance is documented.

**Goal:** Procurement and auditors can see a single register of rules, linked to scenarios and versions; CI enforces presence and shape.

**Exact files to change:**

1. **Create `docs/rule_register.csv`**
   - Header: `rule_id,scenario_id,severity,params_snapshot,owner,last_tested,version`
   - One row per enabled rule (high_value, rapid_velocity, geo_mismatch, structuring_smurfing, sanctions_keyword, high_risk_country, network_ring). scenario_id from `docs/scenario_library.md` (e.g. high_value_single, smurfing_velocity, sanctions_keyword, high_risk_country, geo_mismatch, structuring_just_under, network_ring). severity from config or default (e.g. high/medium). params_snapshot short JSON or key params. owner e.g. "aml-team". last_tested date. version from rule RULE_HASH or "1.0".

2. **Add validation (optional but recommended)**
   - **Script:** `scripts/validate_rule_register.py`: read CSV, assert header, assert rule_id column contains at least the rule IDs from `get_all_rules()` (or from a fixed list). Exit 0/1.
   - **Makefile:** target `validate-rule-register` that runs the script; optionally add to `make ci` or document in README.

**Acceptance criteria (measurable):**

- File `docs/rule_register.csv` exists.
- Header includes `rule_id`, `scenario_id`, `severity`.
- At least 7 rows (one per enabled rule).
- Optional: `python scripts/validate_rule_register.py` exits 0.

**Tests to add (or extend):**

- No new pytest required if validation is a script; alternatively: `tests/test_rule_register.py` that asserts file exists, has required columns, and row count >= number of enabled rules.

**Verification command:**

```bash
./scripts/ci.sh
# and optionally:
python scripts/validate_rule_register.py
# or: make validate-rule-register
```

This patch advances procurement readiness by closing the “rule register missing” blocker (audit pack completeness) with minimal code and a clear artifact.
