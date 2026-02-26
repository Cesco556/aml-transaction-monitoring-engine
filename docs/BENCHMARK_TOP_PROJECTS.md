# Benchmark: Top Projects & Resources (Atlas)

**Purpose:** Longlist of 10–20 high-value public projects/resources for AML TM, fraud decisioning, case workflows, sanctions screening, and graph analytics. Last discovery: 2025-02.

**Scope:** Public sources only; prioritised last ~24 months; max 20 candidates → best 5 selected and scored.

---

## 1. Our Current Capability Snapshot (Evidence)

Before benchmarking others, our repo’s current state is summarised below with evidence pointers.

| Capability | Evidence (file path / heading) |
|------------|--------------------------------|
| **README & positioning** | `README.md` — Portfolio overview, architecture ASCII, quickstart, commands table, reproducibility § |
| **Audit pack** | `docs/GOVERNANCE/AUDIT_PLAYBOOK.md` — “Why was transaction X flagged?”; `docs/GOVERNANCE/MRM.md` — SR 11-7 style governance |
| **Rule register** | `docs/rule_register.csv` — rule_id, scenario_id, severity, params_snapshot, owner, last_tested, version |
| **Scenario library** | `docs/scenario_library.md` — typologies → expected rules, adversarial coverage, determinism |
| **CI proof** | `docs/MAKE_CI_PROOF.md` — command `./scripts/ci.sh`, result summary (ruff, black, mypy, pytest 91 passed) |
| **Reproduce bundle** | `README.md` § Reproducibility; `src/aml_monitoring/reproduce.py` — export by correlation_id; `docs/GOVERNANCE/AUDIT_PLAYBOOK.md` § 3–5 |
| **Governance** | `docs/GOVERNANCE/` — MRM, TUNING, DATA_QUALITY, AUDIT_PLAYBOOK; `docs/RULE.md` — single source of truth |
| **API** | `src/aml_monitoring/api.py` — GET /alerts, /transactions/{id}, /network/account/{id}, /health; POST /score; PATCH /alerts/{id} |
| **Cases API** | `src/aml_monitoring/cases_api.py` — POST/GET/PATCH /cases, GET /cases/{id}, POST /cases/{id}/notes |
| **UI** | `scripts/dashboard.py` (Streamlit); `docs/DASHBOARD.md` — tabs: Overview, Alerts, Cases, SAR Report |
| **Demo** | `scripts/demo.sh` — Docker stack, seed, run-rules, PATCH alert, POST case, reproduce-run; `RUNBOOK.md` § Demo |
| **Tests** | `tests/` — test_rules, test_scoring, test_api, test_case_lifecycle, test_audit_chain, test_determinism, test_adversarial_evasion, test_ingest_rejects, test_reproduce_run_produces_bundle_and_audit_log |
| **Rule validation** | **DONE:** `scripts/validate_rule_register.py` checks docs/rule_register.csv; run in CI via `make ci` (see Makefile, docs/MAKE_CI_PROOF.md). |

**Summary:** We have ingest (CSV/JSONL, idempotent), rules engine (6 rules), scoring, alerts, cases (lifecycle + API), audit (correlation_id, config_hash, AuditLog, hash chain), reproduce-run bundle, governance docs, scenario library, rule register (validated in CI), and Streamlit dashboard. Gaps vs benchmarks: no badges in README; demo/screenshots not formalised in a positioning doc.

---

## 2. Candidate Longlist (Max 20)

| # | Name | Link | Type | Last update (approx) | Evidence snippet |
|---|------|------|------|----------------------|------------------|
| 1 | Marble | https://github.com/checkmarble/marble | repo | 2024–2025 | README: “Transaction Monitoring, AML Screening and Case investigation”; docker-compose.yaml; CONTRIBUTING.md, SECURITY.md |
| 2 | Jube AML | https://github.com/jube-home/aml-fraud-transaction-monitoring | repo | 2024–2026 | README: real-time TM, ML, rule-based, case management; docs/; .github/workflows/; Jube.Case/, Jube.Engine/, Jube.Preservation/ |
| 3 | OpenSanctions Yente | https://github.com/opensanctions/yente | repo | 2024 | README: “entity search and bulk matching”; docs/; tests/; mkdocs.yml; pyproject.toml |
| 4 | Trench | https://github.com/trytrench/trench | repo | 2024 | README: “fraud and abuse prevention”; dashboard/, docs/, docker-compose; “under development” |
| 5 | IBM AMLSim | https://github.com/IBM/AMLSim | repo | 2021+ | README: synthetic AML transaction data; scripts/validation/validate_alerts.py; Wiki Quick Introduction, Directory Structure |
| 6 | OpenSanctions (data) | https://github.com/opensanctions/opensanctions | repo | 2024 | Data pipeline for sanctions/PEP; used by yente |
| 7 | FollowTheMoney | https://followthemoney.tech/ | tool/docs | ongoing | Data model for investigations; OpenAleph integration |
| 8 | eBay xFraud | https://github.com/eBay/xFraud | repo | older | Fraud detection; Apache-2.0 |
| 9 | PyPanther | https://github.com/panther-labs/pypanther | repo | 2024 | Python detection rules framework; Apache-2.0 |
| 10 | FATF | https://www.fatf-gafi.org/ | standard | 2024 | Guidance RBA, national risk assessment, VA update; authoritative for AML TM expectations |
| 11 | Tazama | https://github.com/tazama-lf/docs | repo/docs | recent | Open source transaction monitoring; ISO20022 |
| 12 | Wolfsberg | https://www.wolfsberg-principles.com/ | guideline | ongoing | Industry guidelines for AML; referenced by Jube docs |

*Stopped at 12 candidates; disqualified: toy repos with no tests, no governance; abandoned (3+ years no meaningful updates) except IBM AMLSim as canonical reference.*

---

## 3. Score Table (0–5 per criterion)

| Candidate | Prod readiness | Docs quality | Governance (rule reg / scenario / version / audit) | Investigator UX (alerts/cases/network/reports) | Test discipline (CI / determinism / adversarial / replay) | Maintenance (activity/issues/releases) |
|-----------|----------------|--------------|-------------------------------------------------------------------|------------------------------------------------|-------------------------------------------------------------|----------------------------------------|
| Marble | 5 | 4 | 4 | 5 | 3 | 5 |
| Jube AML | 4 | 4 | 3 | 4 | 3 | 4 |
| OpenSanctions Yente | 4 | 5 | 3 | 2 | 4 | 4 |
| Trench | 3 | 4 | 2 | 4 | 2 | 4 |
| IBM AMLSim | 3 | 3 | 2 | 1 | 4 | 3 |
| OpenSanctions (data) | 4 | 4 | 3 | 1 | 3 | 4 |
| FollowTheMoney | 3 | 4 | 2 | 2 | 2 | 3 |
| eBay xFraud | 3 | 3 | 2 | 2 | 3 | 2 |
| PyPanther | 3 | 3 | 2 | 1 | 4 | 3 |
| FATF | N/A (ref) | 5 | 5 | N/A | N/A | 5 |
| Tazama | 3 | 3 | 2 | 2 | 2 | 3 |
| Wolfsberg | N/A (ref) | 5 | 5 | N/A | N/A | 5 |

---

## 4. Best 5 + Justification

1. **Marble (checkmarble/marble)**  
   **Evidence:** README lists transaction monitoring, screening, case investigation, audit trail, “searchable and unalterable audit logs,” Docker quick start, CONTRIBUTING.md, SECURITY.md.  
   **Justification:** Highest production readiness and investigator UX in one place; governance (audit trail, RBAC) and active maintenance; weaker on explicit rule registry and scenario docs in repo.

2. **Jube (jube-home/aml-fraud-transaction-monitoring)**  
   **Evidence:** README “workflow-driven case management,” “full audit trails,” Jube.Preservation/, Jube.Case/, docs/Getting Started, docker-compose.  
   **Justification:** Full AML TM + case + audit + ML; good docs and structure; rule governance less explicit than our rule_register/scenario_library.

3. **OpenSanctions Yente (opensanctions/yente)**  
   **Evidence:** README “entity search and bulk matching,” FollowTheMoney entities, docs/, tests/, pre-commit, pyproject.toml.  
   **Justification:** Best-in-class sanctions/PEP matching API and docs; complementary to TM (screening); high doc and test discipline.

4. **IBM AMLSim (IBM/AMLSim)**  
   **Evidence:** README + Wiki “Quick Introduction,” “Directory Structure,” scripts/validation/validate_alerts.py, conf.json, synthetic AML patterns.  
   **Justification:** Canonical synthetic AML data and validation pattern; use for adversarial/demo data and “reproduce bundle” test fixtures.

5. **FATF (standard)**  
   **Evidence:** fatf-gafi.org — Guidance on risk-based supervision, national risk assessment 2024.  
   **Justification:** Authoritative reference for governance and audit expectations; no code but essential for “enterprise-grade” positioning.

---

## 5. Disqualifiers Applied

- **Abandoned:** Excluded repos with no meaningful updates in 3+ years unless canonical (AMLSim retained).
- **Toy/demo:** Excluded projects with no tests and no governance artifacts.
- **Low-trust:** Excluded SEO-only content without corroboration from repo or official docs.

---

*Next: see `docs/BENCHMARK_FINDINGS_AND_ACTIONS.md` for extracted patterns and gap→fix matrix.*
