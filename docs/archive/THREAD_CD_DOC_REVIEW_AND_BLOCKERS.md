---
**HISTORICAL (pre-P0–P2 implementation). Current state: see docs/IMPLEMENTATION_DELIVERABLE.md and docs/DOCS_CONSISTENCY_AUDIT.md.**

---
# Repo Engine Review: THREAD_CD_FULL_AUDIT_AND_2026_PLAN.md

**Document under review:** `docs/THREAD_CD_FULL_AUDIT_AND_2026_PLAN.md`  
**Goal:** Validate doc vs code; extract missing details; list blockers and exact next patches/tests.

---

## A) DOC ↔ CODE CONSISTENCY CHECK (MANDATORY)

### 1) Does the current code still silently drop bad ingest rows?

**No.** The code no longer silently drops bad rows; rejects are counted and reasons persisted.

**Evidence:**

- **csv_ingest.py**
  - `rows_rejected` and `reject_reasons` created: lines 79–80 (`rows_rejected = 0`, `reject_reasons: list[str] = []`), line 81 (`max_reject_reasons = 500`).
  - Increment and append: lines 94–96 (missing_iban), lines 107–110 (parse_error).
  - AuditLog details: lines 215–226 — `details` dict; when `rows_rejected` non-zero, `details["rows_rejected"] = rows_rejected`, `details["reject_reasons"] = reject_reasons` (lines 224–225); written to `AuditLog(..., details_json=details)` (lines 227–234).

- **jsonl_ingest.py**
  - Same pattern: lines 77–79 (counters), 93–96 (missing_iban), 106–109 (parse_error), 214–225 (details with rows_rejected/reject_reasons when non-zero).

- **Tests that assert behaviour:**
  - `tests/test_ingest_rejects.py`: `test_csv_ingest_rejects_missing_iban_audit_has_reject_reasons` (asserts `details["rows_rejected"] == 2`, `details["reject_reasons"]`), `test_csv_ingest_rejects_parse_error_audit_has_reject_reasons`, `test_csv_ingest_no_rejects_when_all_valid_audit_has_no_reject_keys`, `test_jsonl_ingest_rejects_audit_has_reject_reasons`.

**Doc updates required (every place that still claims silent drop or no rows_rejected):**

| Location in doc | Current text (or gist) | Required change |
|-----------------|------------------------|-----------------|
| **Section 0 REPO EVIDENCE INDEX** | csv_ingest: "no rows_rejected/reasons"; jsonl: "same silent drop" | State: rows_rejected and reject_reasons are created and written to audit when rejects occur (csv_ingest 79–81, 94–96, 107–110, 215–226; jsonl 77–79, 93–96, 106–109, 214–225). Tests: test_ingest_rejects.py. |
| **Section 1 CURRENT STATE — Validation** | "Ingest: no schema validation; parse failures drop row." | "Ingest: no full schema validation; parse/validation failures increment rows_rejected and append reason (missing_iban, parse_error:ExceptionType); persisted in audit details_json when rows_rejected > 0." |
| **Section 1 — Bad rows** | "Dropped silently; not quarantined; not logged per row" | "Rejected rows are counted (rows_rejected) and reasons listed (reject_reasons, cap 500); persisted in ingest audit details_json. Not quarantined to table/file; no per-row reject log." |
| **Section 2 THREAD B table row 1** | "drops bad rows silently" / "Audit only has rows_read/rows_inserted" | "FIXED: rows_rejected and reject_reasons are now persisted in ingest audit details_json (csv_ingest 215–226, jsonl 214–225). Tests: test_ingest_rejects.py." Set status to **FIXED** or **PARTIAL** (no quarantine). |
| **Section 3 ADDITIONAL WEAKNESSES** | "Silent ingest rejections; no reject count or reasons" | "Reject count and reasons now in audit (P0.1 done). Remaining: no quarantine table/file; no replay of rejects." |
| **Section 4.1 Dirty data** | "no silent drop" | Keep as expected behaviour; "Where in code" can note implementation is in csv_ingest/jsonl_ingest (rows_rejected, reject_reasons). |
| **Section 6 P0.1** | "no silent drop" | Mark P0.1 **DONE**; acceptance criteria met (details_json has rows_rejected, reject_reasons). |
| **Section 7 KILLER DIFFERENTIATORS #1** | "no silent loss" | Keep; implementation done. |

### 2) Confirm current run_rules behaviour

- **Does it load all transactions into memory?**  
  **Yes.**  
  - `src/aml_monitoring/run_rules.py` lines 42–44:
    - `stmt = select(Transaction).order_by(Transaction.id)`
    - `for txn in session.execute(stmt).scalars().all()`  
  - `.all()` loads the full result set into memory; no LIMIT or chunking.

- **Chunking/checkpoint/resume:**  
  **MISSING.** There is no checkpoint persistence, no last_processed_id, no resume logic. Single `session_scope()` block processes all rows.

**Doc:** Section 1 and Section 2 (hypothesis 7) and Section 3 (run_rules chunking) are consistent with code.

### 3) Confirm reproduce bundle contents in reproduce.py

- **Does the bundle include transaction payloads?**  
  **No.**

- **Evidence:** `src/aml_monitoring/reproduce.py` builds `bundle` with: `metadata`, `config` (config_hashes, rules_versions, engine_versions), `audit_logs`, `alerts` (via `_alert_to_dict`: id, transaction_id, rule_id, severity, score, reason, evidence_fields, config_hash, rules_version, engine_version, correlation_id, status, disposition, created_at, updated_at), `cases` (via `_case_to_dict`), `network` (edge_count, edges). There is no key for transaction rows; alerts reference `transaction_id` only.

- **Why replay is impossible without DB:** Replay requires the exact transaction rows (account_id, ts, amount, currency, counterparty, etc.) that produced the alerts. The bundle does not contain those rows, so a recipient cannot re-run rules on the same inputs without access to the same DB or a separate transaction export.

**Doc:** Section 1 (Reproduce), Section 3 (Reproduce bundle), and Section 4.5 are consistent with this.

---

## B) ANSWERS TO QUESTIONS (REPO EVIDENCE ONLY)

### B1) Data Quality & Ingest

1) **Complete list of reject reasons produced today; normalized enums or raw strings?**  
   - **Reasons:** `missing_iban` (when iban_or_acct empty after strip); `parse_error:{type(e).__name__}` (e.g. `parse_error:ValueError`, `parse_error:KeyError`, `parse_error:JSONDecodeError`).  
   - **Form:** Raw strings in a list; not normalized enums.  
   - **Evidence:** csv_ingest.py 96, 110; jsonl_ingest.py 95, 108.

2) **Are rejects capped? How avoid losing critical evidence while providing totals?**  
   - **Capped at 500:** `max_reject_reasons = 500` (csv_ingest 81, jsonl 79). Append only if `len(reject_reasons) < max_reject_reasons`.  
   - **Totals:** `rows_rejected` is always the full count (incremented for every reject). So total reject count is never lost; only the list of reason samples is capped.  
   - **Evidence:** csv_ingest 79, 95, 108; jsonl 77, 94, 107.

3) **Where do rejects live besides AuditLog? Quarantine table/file?**  
   - **MISSING.** Rejects exist only in AuditLog.details_json (rows_rejected, reject_reasons). No quarantine table, no reject file, no separate store.

4) **Can rejects be replayed after a parsing/validation fix?**  
   - **MISSING.** There is no CLI/command to re-ingest rejected rows. Rejected row content is not stored; only reason strings are. So replay after a fix would require the original file and a separate “re-ingest from file” run (no “replay rejects” flow).

5) **Schema validation at ingest time (not API)?**  
   - **Partial.** Ingest does not use Pydantic. It does: required iban (reject if empty); ts parsed via _parse_ts (ValueError → reject); amount float() (ValueError → reject); currency strip()[:3]; base_risk float(); optional fields defaulted. No explicit schema (e.g. required field list per format), no ISO currency validation, no country code validation.  
   - **Evidence:** csv_ingest 88–111; jsonl 87–110.

6) **Does ingest enforce ISO currency codes?**  
   - **MISSING.** Currency is `(row.get("currency") or "USD").strip()[:3]` (csv 100) and `(obj.get("currency") or "USD")[:3]` (jsonl 99). Any 3-character (or truncated) string is accepted; no check against ISO 4217.

### B2) Determinism & Reproducibility

1) **Determinism test: same input + same config → identical (transaction_external_id, rule_id)?**  
   - **MISSING.** No test in repo that runs ingest + run_rules twice with same input/config and asserts identical set of (external_id, rule_id) or alert count/rule_ids.  
   - **Evidence:** grep for "determinism|deterministic|identical" in tests → no matches.

2) **Is correlation_id deterministic per run?**  
   - **No.** It is random (UUID) unless set by caller.  
   - **Evidence:** `audit_context.py` 26–27: if not set, `cid = str(uuid.uuid4())`. CLI sets it at start of each command: `set_audit_context(str(uuid.uuid4()), ...)` (e.g. cli.py 47, 65, 76). So each run gets a new correlation_id; it is stored on Alert and AuditLog and used for traceability (list/filter by correlation_id).

3) **Can reproduce bundle replay fully without DB?**  
   - **MISSING.** Bundle has no transaction payloads (see A.3). Replay without DB is impossible.

4) **Configs in bundle: full YAML or only config_hash?**  
   - **Only hashes/versions.** Bundle has `config.config_hashes`, `config.rules_versions`, `config.engine_versions` (reproduce.py 129, 201–203). No full YAML. Replay would need to obtain the exact config by some other means (e.g. same repo version and config path); not in bundle.

### B3) Chunking / Backpressure / Resume

1) **If chunking exists: prove invariants.**  
   - Chunking does **not** exist in run_rules (see A.2).

2) **If chunking does not exist: smallest implementation plan and exact files.**  
   - **Files to change:** `src/aml_monitoring/run_rules.py`.  
   - **Plan:** (a) Add config/chunk_size (e.g. 5000). (b) Loop: `select(Transaction).where(Transaction.id > last_id).order_by(Transaction.id).limit(chunk_size)`; process chunk; set `last_id = chunk[-1].id`; write to audit details e.g. `chunk_index`, `last_processed_id`, `processed_in_chunk`. (c) Optionally persist last_processed_id in a small table or in audit entity_id/details for resume. (d) Resume: read last_processed_id, start from `id > last_processed_id`.  
   - **Tests to add:** Integration test that run_rules with chunk_size=2 produces same total alerts as no chunking (same data); test that resume from midpoint does not duplicate or skip (e.g. run to chunk 1, “fail”, resume from last_processed_id, assert total processed = full set).

### B4) Rule Governance

1) **Do alerts include per-rule hash/version?**  
   - **No.** Alert has `rules_version` (single global RULES_VERSION from __init__.py), `config_hash`, `engine_version`, and `evidence_fields` (rule-specific dict). No per-rule hash or version in schema or evidence_fields.  
   - **Evidence:** models.py Alert 85–88; run_rules.py 71–74 (rules_version=RULES_VERSION); no RULE_HASH or per-rule version in rules/*.

2) **Is RULES_VERSION tied to actual code version (git tag, build hash)?**  
   - **MISSING.** `src/aml_monitoring/__init__.py`: `RULES_VERSION = "1.0.0"`, `ENGINE_VERSION = "0.1.0"`. Hardcoded; not derived from git or build.

3) **rule_register.csv and scenario_library.md in docs/?**  
   - **MISSING.** No files `docs/rule_register.csv` or `docs/scenario_library.md` (glob search returned 0).

4) **Does tuning.py produce per-rule metrics or only thresholds?**  
   - **Only thresholds.** tuning.py computes and writes threshold params (high_value.threshold_amount, structuring_smurfing.threshold_amount, rapid_velocity.min_transactions/window_minutes) to config fragment. No precision/recall, no FP rate, no effectiveness metrics.  
   - **Evidence:** tuning.py 26–73, 76–89.

### B5) Lists discipline (sanctions / high-risk)

1) **Do sanctions/high-risk configs include list_version and effective_date?**  
   - **MISSING.** config/default.yaml has `rules.sanctions_keyword.keywords` and `rules.high_risk_country.countries`; no list_version or effective_date. Rules read only keywords/countries.  
   - **Evidence:** config/default.yaml 35–45; sanctions_keyword.py 12–13; high_risk_country.py 12–13.

2) **When a list-based rule fires, is version/effective_date stored on the alert?**  
   - **MISSING.** Alert stores rule_id, reason, evidence_fields (e.g. keyword, country). No list_version or effective_date in evidence or elsewhere.  
   - **Evidence:** sanctions_keyword.py 22–28; high_risk_country.py 20–26; models.Alert 84.

3) **Does config loader fail on placeholder [XX, YY]?**  
   - **MISSING.** get_config() loads YAML and merges; no validation for high_risk_country.countries. default.yaml contains `[XX, YY]` with comment "placeholder"; loader does not fail or warn.  
   - **Evidence:** config.py 46–66; no check for XX/YY.

### B6) Timeliness MI

1) **Where is time-to-disposition computed and stored/exported?**  
   - **MISSING.** Not computed. Alert has created_at and updated_at (models.Alert 92–94); no derived field or report that computes (updated_at - created_at) or “hours_to_disposition”.  
   - **Evidence:** reporting.py select does not include Alert.created_at, Alert.updated_at; records dict (61–75) has no timeliness fields.

2) **Does reporting include created_at, updated_at, hours_to_disposition?**  
   - **No.** generate_sar_report selects Alert.id, transaction_id, rule_id, severity, reason, evidence_fields and Transaction fields; does not select Alert.created_at, Alert.updated_at. JSON/CSV output has no timeliness.  
   - **Evidence:** reporting.py 41–57, 61–76, 85–99.

3) **SLA or backlog metric?**  
   - **MISSING.** No backlog count, no SLA metric, no time-to-triage or time-to-close aggregation.

### B7) Security posture

1) **Do API keys have scopes/roles? Enforcement on PATCH /alerts and POST /cases?**  
   - **No.** auth.py: parse_api_keys_env returns name→key; require_api_key validates key and sets actor (name). No scope or role; no check per endpoint. PATCH /alerts and POST /cases only require valid API key (require_api_key).  
   - **Evidence:** auth.py 12–26, 29–46; api.py 174; cases_api.py 41, 165.

2) **Separate read-only keys?**  
   - **MISSING.** All keys have same capability; GET /alerts and GET /transactions are unauthenticated in code (no Depends(require_api_key) on list_alerts or get_transaction). So there are no read-only keys.

3) **Secrets stored safely and rotated?**  
   - Keys come from env AML_API_KEYS (.env / environment). No vault; rotation is manual (env change). **Limitation;** minimal upgrade: document rotation procedure; optional integration with a secrets backend (e.g. env from vault at startup).

4) **PII redaction in reports/logs?**  
   - **MISSING.** Reports include counterparty, account_id, etc. (reporting.py 51–54, 72–74). No redaction or masking documented or implemented. Logs use standard logging; no PII redaction.

### B8) Investigator usefulness

1) **Can investigator see: customer context, transaction history, linked entities, network neighborhood from API/UI?**  
   - **Partial.** API: GET /transactions/{id} returns transaction + alerts (no customer); GET /alerts (list); GET /cases (list/detail with items/notes). No GET /customers or /accounts; no “transaction history for account”; no “linked entities” or “network neighborhood” endpoint. Dashboard (Streamlit) exists but was not fully inspected for these views.  
   - **Evidence:** api.py 239–254 (get_transaction); no /customers, /accounts, /network in api.py or cases_api.py.

2) **GET /network/account/{id}?**  
   - **MISSING.** No such route. api.py and cases_api.py have no /network path.  
   - **Evidence:** grep "/network|/health" in src/aml_monitoring → no matches.

3) **Does any rule beyond network_ring use RelationshipEdge?**  
   - **No.** Only NetworkRingIndicatorRule uses RelationshipEdge (via ring_signal in network/metrics.py).  
   - **Evidence:** grep RelationshipEdge|ring_signal in src/aml_monitoring/rules → only network_ring.py.  
   - **Single best next network-based rule:** Fan-out / mule: accounts that send to many distinct counterparties in a short window (high out-degree on RelationshipEdge account→counterparty). Uses existing edges; no new schema.

---

## C) MISSING/BLOCKERS (RANKED)

| # | Blocker | Why it blocks procurement/audit | Repo evidence | Smallest fix + tests |
|---|---------|----------------------------------|---------------|----------------------|
| 1 | Reproduce bundle has no transaction payloads | Auditors cannot replay run without DB; reproducibility claim is weak | reproduce.py: bundle has alerts (transaction_id), cases, edges, audit_logs; no transactions array | Add to reproduce_run: for each distinct transaction_id in alerts, fetch Transaction row and append to bundle["transactions"] with same schema as API (id, account_id, ts, amount, currency, counterparty, country, etc.). Test: reproduce_run then assert "transactions" in bundle and len(bundle["transactions"]) >= 1 when alerts exist. |
| 2 | No time-to-disposition in reporting | Buyers/regulators ask for timeliness MI immediately | reporting.py: select does not include Alert.created_at/updated_at; records have no timeliness | In generate_sar_report add Alert.created_at, Alert.updated_at to select and to records; add hours_to_disposition (timedelta(updated_at - created_at).total_seconds()/3600 if updated_at else None). Test: assert report JSON has created_at, updated_at, hours_to_disposition for at least one alert. |
| 3 | run_rules loads all transactions (no chunking) | Production OOM and no resume after failure | run_rules.py 42–44: select(Transaction).order_by(Transaction.id); for txn in session.execute(stmt).all() | Chunk by Transaction.id (config chunk_size); write last_processed_id and chunk_index to run_rules audit details; optional resume from last_processed_id. Test: same data chunk_size=100 vs no limit → same alert count; resume test. |
| 4 | Config accepts placeholder [XX, YY] | Production could ship with non-operational high-risk list | config/default.yaml 44–45 countries: [XX, YY]; config.py get_config has no validation | After load/merge, validate rules.high_risk_country.countries: if "XX" in or "YY" in, raise ValueError or log critical and require explicit override. Test: get_config with default that has XX/YY fails or warns. |
| 5 | No per-rule version/hash on alerts | Cannot prove which rule code produced an alert | Alert has rules_version only; rules/* have no RULE_HASH | Each rule module exports RULE_VERSION or RULE_HASH; run_rules stores in evidence_fields when rule fires. Test: assert alert.evidence_fields or audit contains rule version for one rule. |
| 6 | No list_version/effective_date for sanctions/high-risk | Cannot prove which list was in effect at alert time | sanctions_keyword.py, high_risk_country.py: no list_version in config or evidence | Add to config list_version and effective_date; rules pass into evidence_fields when firing. Test: fire rule, assert evidence has list_version/effective_date. |
| 7 | No determinism test | Same input → same output not verified | No test file or test name with determinism | Test: ingest same CSV twice (fresh DB each time), run_rules twice; assert set of (transaction.external_id, rule_id) or alert counts/rule_id set identical. |
| 8 | No GET /health | Ops/monitoring cannot check liveness | api.py: no /health route | Add GET /health returning 200 and optional {"status":"ok","version":ENGINE_VERSION}. Test: client.get("/health") status 200. |
| 9 | API keys have no scopes/roles | Cannot restrict e.g. read-only or analyst vs admin | auth.py: only name→key; require_api_key returns actor | Add optional scope per key (e.g. in env or config); require_scope("alerts:write") on PATCH /alerts and POST /cases. Test: key with read_only scope gets 403 on PATCH. |
| 10 | rule_register.csv and scenario_library.md missing | Audit pack incomplete; rule governance not documented | docs/: no rule_register.csv, no scenario_library.md | Create docs/rule_register.csv (rule_id, scenario_id, severity, params, owner, last_tested, version) and docs/scenario_library.md (scenario_id, description, expected_rule or OUT_OF_SCOPE). Test: files exist; CI can optionally validate CSV columns. |

---

## D) REQUIRED PATCHES + TESTS (NEXT P0 ONLY)

**Single best next patch:** Add **SAR timeliness to report** (time-to-disposition in export). This is high impact for buyers, small change, and unblocks “timeliness MI” immediately.

### File changes

- **`src/aml_monitoring/reporting.py`**
  - In the `select()`, add `Alert.created_at`, `Alert.updated_at` (and keep existing columns).
  - When building each record (loop over rows), add:
    - `created_at`: serialize row’s Alert.created_at (isoformat).
    - `updated_at`: serialize row’s Alert.updated_at if present.
    - `hours_to_disposition`: if updated_at and created_at are both present, compute `(updated_at - created_at).total_seconds() / 3600` and round (e.g. 2 decimals); else None.
  - Include these in the JSON output (they can be omitted from CSV or added as extra columns for MI).

### Tests

- **New test in `tests/test_integration.py` or `tests/test_reporting.py`:**
  - Create DB with one alert; set alert.updated_at to created_at + timedelta(hours=2); flush.
  - Call generate_sar_report(session, out_dir, ...).
  - Load generated JSON; find the alert in the alerts array; assert `created_at` and `updated_at` are present; assert `hours_to_disposition` is present and approximately 2.0 (e.g. 1.99 <= x <= 2.01).

### Acceptance criteria

- SAR report JSON includes for each alert: `created_at`, `updated_at`, and `hours_to_disposition` (float or null).
- When an alert has both timestamps, `hours_to_disposition` is (updated_at - created_at) in hours.
- Existing report generation and audit log behaviour unchanged.

### Verification command

```bash
poetry run pytest tests/test_reporting.py tests/test_integration.py -v -k "report or timeliness"
# or
make test
```

After implementation, add to the doc (Section 1 and B6): “Time-to-disposition is computed in generate_sar_report and exported as hours_to_disposition in the SAR JSON.”

---

## E) IMPLEMENTATION STATUS (POST-P0–P2)

The following items from sections A–D have been **implemented** and are now **FIXED** in code and tests. Evidence is in `docs/IMPLEMENTATION_DELIVERABLE.md`.

| Former blocker / question | Status | Evidence (paths + tests) |
|---------------------------|--------|---------------------------|
| A.2 run_rules loads all / no chunking | **FIXED** | run_rules.py: chunk by Transaction.id, last_processed_id in AuditLog details; cli --resume. test_run_rules.py: test_chunk_sizes_produce_identical_alerts, test_resume_no_duplicates_no_skips |
| A.3 Reproduce bundle has no transaction payloads | **FIXED** | reproduce.py: bundle["transactions"], bundle["config"]["resolved"]. test_integration test_reproduce_run asserts transactions and config.resolved |
| B2.1 Determinism test | **FIXED** | tests/test_determinism.py: test_same_input_twice_same_alert_set |
| B2.3 Reproduce replay without DB | **FIXED** | Bundle now has transactions + config.resolved; replay script not added (bundle is self-contained) |
| B2.4 Config in bundle only hashes | **FIXED** | bundle["config"]["resolved"] = full merged config |
| B3 Chunking / resume | **FIXED** | run_rules.py chunk loop, checkpoint, resume_from_correlation_id; tests above |
| B4.1 Per-rule hash on alerts | **FIXED** | rules/base.py get_rule_hash(); run_rules evidence_fields["rule_hash"]. test_alerts_include_per_rule_hash_in_evidence |
| B5.1–B5.2 list_version / effective_date | **FIXED** | config default list_version/effective_date; sanctions_keyword.py, high_risk_country.py evidence. test_rules test_sanctions_evidence_has_list_version..., test_high_risk_country_evidence_has_list_version... |
| B5.3 Config placeholder XX/YY | **FIXED** | config.py validate_high_risk_country(); get_config() calls it. test_config test_config_rejects_placeholder_xx_yy |
| B6.1–B6.2 Timeliness in report | **FIXED** | reporting.py created_at, updated_at, hours_to_disposition. test_sar_report_includes_timeliness_and_hours_to_disposition |
| B7.1–B7.2 API scopes / read-only keys | **FIXED** | auth.py key_to_scope, require_api_key_write; PATCH /alerts, POST/PATCH cases use it. test_read_only_key_gets_403_on_patch_alerts |
| B8.2 GET /network/account/{id} | **FIXED** | api.py GET /network/account/{account_id}; edges + ring_signal. test_network_account_returns_edges |
| C.1 Reproduce bundle transactions | **FIXED** | See A.3 |
| C.2 Time-to-disposition | **FIXED** | See B6 |
| C.3 run_rules chunking | **FIXED** | See A.2 / B3 |
| C.4 Config XX/YY | **FIXED** | See B5.3 |
| C.5 Per-rule hash | **FIXED** | See B4.1 |
| C.6 List version/effective_date | **FIXED** | See B5 |
| C.7 Determinism test | **FIXED** | See B2.1 |
| C.8 GET /health | **FIXED** | api.py GET /health; test_health_returns_200_and_version |
| C.9 API key scopes | **FIXED** | See B7 |
| C.10 scenario_library.md | **FIXED** | docs/scenario_library.md created; test-adversarial, test-determinism, test-scenario in Makefile |

**Still missing (unchanged from original ranking):** RULES_VERSION not tied to git/build; rule_register.csv; reject replay/quarantine; ISO currency validation; PII redaction; optional auth on GET; full replay script from bundle; SLA/backlog metrics. See IMPLEMENTATION_DELIVERABLE.md “What is still MISSING/BLOCKING” for top 10.
