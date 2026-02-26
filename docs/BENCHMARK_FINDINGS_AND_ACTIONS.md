# Benchmark Findings and Actions (Atlas)

**Purpose:** Evidence-based patterns from the Best 5, gap→fix matrix for our repo, single highest-ROI upgrade, and top 5 provable differentiators.

**Source:** `docs/BENCHMARK_TOP_PROJECTS.md` (candidates + Best 5).

---

## 1. Winning Patterns (Evidence-Based)

*No claim without citation (repo path or doc heading).*

### 1.1 Architecture pattern

| Source | Pattern | Citation |
|--------|---------|----------|
| Marble | Docker Compose quick start; “connect to any internal systems”; API + front | Marble README § Quick start, “Flexible: Connect Marble to any of your internal systems” |
| Jube | Stateless scalable; Redis real-time state; PostgreSQL durable; HTTP + AMQP | Jube README § “Real-Time Transaction Monitoring,” “Durable storage and audit logs with PostgreSQL” |
| Yente | FastAPI, async Python, env-configured index (OpenSearch/Elasticsearch) | Yente README § “Development,” “YENTE_INDEX_URL” |
| **Our repo** | CSV/JSONL → ingest → SQLite/Postgres; CLI + FastAPI; Alembic for Postgres | `README.md` § Architecture (ASCII); `docs/ARCHITECTURE.md` |

### 1.2 Rule governance pattern (versioning, rule registry, tuning/effectiveness)

| Source | Pattern | Citation |
|--------|---------|----------|
| Marble | “Audit Trail: searchable and unalterable audit logs”; “detection program” | Marble README § Features |
| Jube | “Configuration preservation”; “back up, restore, and migrate rules, workflows, and ML settings” | Jube README § “Cloud-Native” |
| FATF | Risk-based supervision; effective systems and controls | FATF 2024 guidance (risk-based supervision) |
| **Our repo** | config_hash, rules_version, engine_version on alerts; MRM, TUNING; rule_register.csv; scenario_library.md | `docs/GOVERNANCE/MRM.md`; `docs/rule_register.csv`; `docs/scenario_library.md`; `docs/RULE.md` |

*Explicit rule registry (CSV) with scenario mapping and CI validation is a differentiator; Marble/Jube do not publish an equivalent in-repo artifact.*

### 1.3 Investigation workflow pattern (triage → case lifecycle → evidence bundle → reporting)

| Source | Pattern | Citation |
|--------|---------|----------|
| Marble | “Investigation suite: investigate alerts in one unified case manager to explore, annotate & act” | Marble README § Features |
| Jube | “Workflow-driven AML and fraud case management with automated escalation, full audit trails and document versioning” | Jube README § “Case Management for Compliance” |
| **Our repo** | Case status NEW→INVESTIGATING→ESCALATED→CLOSED; PATCH alert disposition; reproduce-run bundle | `docs/RULE.md` § Case lifecycle; `src/aml_monitoring/reproduce.py`; `docs/GOVERNANCE/AUDIT_PLAYBOOK.md` |

### 1.4 UI/UX pattern (nav, tables, filters, details drawer, graph view)

| Source | Pattern | Citation |
|--------|---------|----------|
| Marble | “embedded analytics,” “direct database access for your BI tools” | Marble README § Reporting & BI |
| Jube | “Workflow-driven dashboards for investigators”; Case.png, CaseManagementListing.png, RuleBuilder.png in repo | Jube repo root: Case.png, CaseManagementListing.png, RuleBuilder.png |
| **Our repo** | Streamlit: Overview (severity), Alerts (paginated), Cases, SAR Report preview | `docs/DASHBOARD.md` § Behaviour; `scripts/dashboard.py` |

### 1.5 Demo pattern (one-command demo, seed data, screenshots/gifs)

| Source | Pattern | Citation |
|--------|---------|----------|
| Marble | “docker compose … up”; “Access to the full Installation guide” | Marble README § Quick start |
| Jube | Copy-paste block: clone, env vars, `docker compose up -d`; screenshots in repo (Landing.png, Case.png, etc.) | Jube README § “Getting Started” |
| **Our repo** | `./scripts/demo.sh` (Docker, seed, run-rules, PATCH alert, POST case, reproduce-run); no README screenshots yet | `scripts/demo.sh`; `README.md` |

### 1.6 Trust pattern (audit pack, replay/reproduce, CI proof)

| Source | Pattern | Citation |
|--------|---------|----------|
| Marble | “Audit Trail: searchable and unalterable audit logs”; SOC 2 Type II | Marble README § Features, Trust center |
| Jube | “Full audit trails for all actions”; “Jube.Preservation” | Jube README; repo Jube.Preservation/ |
| **Our repo** | AUDIT_PLAYBOOK; reproduce-run JSON bundle; config_hash/correlation_id; audit_log hash chain; MAKE_CI_PROOF.md | `docs/GOVERNANCE/AUDIT_PLAYBOOK.md`; `src/aml_monitoring/reproduce.py`; `tests/test_audit_chain.py`; `docs/MAKE_CI_PROOF.md` |

---

## 2. Gap → Fix Matrix

| Benchmark pattern | Our current state | Gap | Exact repo changes | Acceptance criteria | Tests | Docs |
|-------------------|-------------------|-----|--------------------|----------------------|-------|------|
| Rule register validated in CI | rule_register.csv present; validate_rule_register.py exists; run in CI (Makefile, tests/test_rule_register.py). **DONE.** | — | — | `make ci` fails if rule_register missing/invalid | test_rule_register.py | README: “Rule register validated in CI” |
| One-command demo in README | demo.sh exists; README points to RUNBOOK § Demo | README does not show single copy-paste “run demo” | Add “One-command demo” subsection: Docker + `./scripts/demo.sh` with exact commands | User can copy-paste and open dashboard + API docs | Existing demo.sh | README, GITHUB_POSITIONING.md |
| Badges (CI, coverage) | make ci; no badges | No visual CI/coverage signal | Add badge placeholders (e.g. “CI: make ci” or link to Actions when added) | Badges appear in README | — | README |
| Screenshots / GIFs | Dashboard exists; no README media | No visual proof of UI | Add 1–2 screenshots (Alerts table, SAR preview) or GIF (demo flow); plan in GITHUB_POSITIONING | README or docs show UI | — | GITHUB_POSITIONING.md plan |
| Explicit “Why different” section | Differentiators in README paragraph | Not a dedicated, artifact-led section | Add “Why this repo is different” with bullets: CI proof, rule register, reproduce bundle, audit chain, adversarial tests | Section cites docs/artifacts | — | README |
| Scenario library ↔ tests | scenario_library.md; adversarial tests exist | No automated link from scenario_id to test | Optional: test that imports scenario_library and asserts expected_rule coverage for key scenarios | Key scenarios have corresponding tests | test_adversarial_evasion, test_determinism | scenario_library.md |

---

## 3. Single Highest-ROI Upgrade (One Patch)

**Choice:** **Integrate rule register validation into CI.**

**Rationale:** Makes governance visible and enforced in one step: “our rules are registered and validated on every run.” No new product feature, minimal code, high signal for enterprise/audit-minded readers.

**Exact repo changes:**

- **Makefile:** Add target `validate-register` that runs `poetry run python scripts/validate_rule_register.py`. Add `validate-register` as dependency of `ci` (e.g. `ci: lint test validate-register`).
- **README:** Under “Conventions & rule base,” add one bullet: “Rule register: `docs/rule_register.csv` is validated in CI (`scripts/validate_rule_register.py`).”
- **Tests:** Add `tests/test_rule_register.py` that runs the validator (e.g. subprocess or import main) and asserts exit code 0 so `make test` also enforces it.

**Acceptance criteria:**

- With current repo, `make ci` succeeds.
- If `docs/rule_register.csv` is removed or missing required columns, `make ci` (or `make test`) fails.

**Verification command:**  
`make ci` then `mv docs/rule_register.csv docs/rule_register.csv.bak && make ci` (expect failure); `mv docs/rule_register.csv.bak docs/rule_register.csv`.

**Docs updates:** README bullet above; optionally one line in `docs/MAKE_CI_PROOF.md` (“CI also runs rule register validation.”).

---

## 4. Top 5 Differentiators We Can Prove With Artifacts

1. **CI proof** — `./scripts/ci.sh` → documented in `docs/MAKE_CI_PROOF.md`; optional: badge in README.
2. **Rule register** — `docs/rule_register.csv` with scenario_id, severity, owner; validated in CI (after patch).
3. **Reproduce bundle** — `aml reproduce-run <correlation_id>` → JSON bundle (audit_logs, alerts, cases, network); doc in AUDIT_PLAYBOOK and README.
4. **Audit chain** — AuditLog prev_hash/row_hash; verification and tamper-detection in `tests/test_audit_chain.py`.
5. **Adversarial + determinism tests** — Scenario library maps typologies to rules; `tests/test_adversarial_evasion.py`, `tests/test_determinism.py`; SAR timeliness in `tests/test_integration.py`.

*Supporting artifacts: config_hash / rules_version / engine_version on alerts; case lifecycle with validated transitions; API-key actor binding (no X-Actor spoof).*

---

*Next: `docs/GITHUB_POSITIONING.md` for README outline, screenshot/GIF plan, demo script, badges, and “Why different” section.*
