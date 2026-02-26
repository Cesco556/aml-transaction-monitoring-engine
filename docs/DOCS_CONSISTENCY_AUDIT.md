# Docs Consistency Audit (Docs Sync Agent)

**Generated:** By scanning repo docs and source evidence. **Purpose:** Mismatches between docs and current implementation; patch plan; checklist.

**Evidence sources:** `src/aml_monitoring/reproduce.py`, `api.py`, `auth.py`, `ingest/csv_ingest.py`, `ingest/jsonl_ingest.py`, `__init__.py`, `Makefile`, `docs/IMPLEMENTATION_DELIVERABLE.md`.

---

## Mismatch table

| File | Heading / location | Current text (short quote) | Correct text | Evidence pointer |
|------|---------------------|----------------------------|--------------|-------------------|
| README.md | Reproducibility § bundle | "metadata, config (config_hashes, rules/engine versions), audit_logs, alerts, cases, and network" | Bundle includes audit_logs, alerts, cases, network, transactions[] (for alerted txns), config.resolved | reproduce.py L145–165, L167, L242, L291 |
| README.md | Portfolio / Architecture | No explicit GET /health, GET /network/account/{id} | API endpoints include GET /health and GET /network/account/{account_id} | api.py L139 (health), L93 (get_network_account) |
| README.md | (none) | API-key auth for mutations | API keys have scopes (read_only/read_write); mutations require read_write | auth.py L17–42, L68–81; IMPLEMENTATION_DELIVERABLE P1.5 |
| docs/GOVERNANCE/MRM.md | Reproducibility | "audit logs, alerts, cases, network summary" | Include transactions[] and config.resolved in bundle description | reproduce.py bundle keys |
| docs/GOVERNANCE/MRM.md | Change control | "Bump … RULES_VERSION in __init__.py" | RULES_VERSION from env AML_RULES_VERSION or git describe; document in release notes | __init__.py L25 |
| docs/GOVERNANCE/DATA_QUALITY.md | (Audit details) | details_json holds counts, IDs, config_hash | Ingest batches: rows_rejected and reject_reasons (capped) in AuditLog.details_json | csv_ingest.py L209–211, L225; jsonl_ingest.py L222–224, L233 |
| docs/BENCHMARK_TOP_PROJECTS.md | Snapshot / Summary | "Rule validation … (not yet in CI)" / "rule register not in CI" | DONE: validated in CI via scripts/validate_rule_register.py and make ci | Makefile ci: lint test validate-register; MAKE_CI_PROOF |
| docs/BENCHMARK_FINDINGS_AND_ACTIONS.md | Gap → Fix matrix | "Rule register validated in CI" row shows Gap / not run in CI | Mark as DONE with evidence | Makefile, tests/test_rule_register.py |

---

## Patch plan

1. **README.md:** (1) Reproducibility § — add transactions[], config.resolved to bundle list. (2) Architecture snapshot or Commands/API — add GET /health, GET /network/account/{account_id}. (3) Add one line on API key scopes (read_only/read_write) and that mutations require read_write.
2. **docs/GOVERNANCE/MRM.md:** (1) Reproducibility bullet — add transactions (for alerted txns) and config.resolved. (2) Change control — add RULES_VERSION from env/git (AML_RULES_VERSION or git describe).
3. **docs/GOVERNANCE/DATA_QUALITY.md:** Under Audit details (or new subsection) — add that ingest records rows_rejected and reject_reasons (capped) in AuditLog.details_json.
4. **docs/BENCHMARK_TOP_PROJECTS.md:** Snapshot table "Rule validation" and Summary — state validated in CI; reference scripts/validate_rule_register.py and docs/MAKE_CI_PROOF.md.
5. **docs/BENCHMARK_FINDINGS_AND_ACTIONS.md:** Gap matrix — mark "Rule register validated in CI" as DONE; add evidence pointer.
6. **docs/archive/:** Create; move THREAD_CD_*.md into archive; add historical banner to each.
7. **docs/CI_RUN_LOG.md:** Create after running CI with command and last 30 lines.

---

## Final consistency checklist

- [x] README: reproduce bundle contents accurate (audit_logs, alerts, cases, network, transactions[], config.resolved).
- [x] README: API includes GET /health, GET /network/account/{account_id}.
- [x] README: API keys scopes (read_only/read_write) and mutations require read_write stated.
- [x] MRM: reproduce wording + RULES_VERSION (env/git) consistent with implementation.
- [x] DATA_QUALITY: rows_rejected and reject_reasons (capped) in AuditLog.details_json documented.
- [x] BENCHMARK_TOP_PROJECTS: rule register validation marked DONE with references.
- [x] BENCHMARK_FINDINGS_AND_ACTIONS: rule register row marked DONE.
- [x] THREAD_CD_* docs in docs/archive/ with historical banner.
- [x] docs/CI_RUN_LOG.md present. CI exit code was 2 (pre-existing lint in src/); see docs/CI_RUN_LOG.md.

---

*Current state reference: docs/IMPLEMENTATION_DELIVERABLE.md.*
