# GitHub Positioning Package (Atlas)

**Purpose:** README outline, screenshot/GIF plan, demo script narrative, badges plan, and “Why this is different” section grounded in verifiable artifacts.

---

## 1. README Outline (Exact Section Headings + Bullet Content)

- **Title:** AML Transaction Monitoring Engine  
- **One-line:** Production-grade AML transaction monitoring MVP: ingest, rules, scoring, alerts, SAR-style reports, case workflow, full audit trail.

- **Portfolio overview (short)**
  - What problem it solves (ingest → rules → alerts → reports; “why was transaction X flagged?”).
  - Key differentiators (idempotent ingest; correlation_id; case lifecycle; governance pack; reproduce-run bundle; API-key auth with actor binding).
  - Architecture snapshot (CSV/JSONL → ingest → DB → rules + scoring → alerts; FastAPI + CLI; Alembic for Postgres).
  - Quickstart: `make ci` → Docker → `./scripts/demo.sh` → dashboard :8501, API :8000/docs. Links: governance, RULE.md.

- **Requirements**  
  - Python 3.11+; macOS or Linux.

- **Quick start**  
  - Clone, `poetry install`, generate synthetic data, ingest, run-rules, generate-reports, optional serve.

- **Exact commands (copy-paste)**  
  - Single block from project root.

- **Run CI locally**  
  - Command: `./scripts/ci.sh`; prerequisites (Poetry); troubleshooting.

- **Terminal setup (Cursor / VS Code)**  
  - Workspace cwd; setup_terminal.sh; note that agent runs in separate env.

- **Architecture (ASCII)**  
  - Existing diagram (data flow).

- **Data flow**  
  - Ingest → run rules → reports → API.

- **Commands reference**  
  - Table: ingest, discover, train, build-network, run-rules, generate-reports, serve-api, simulate-stream, reproduce-run, dashboard.

- **Configuration**  
  - default/dev YAML; env overrides; Postgres; tuned.yaml (train).

- **Detection rules (implemented)**  
  - Table: rule name, description, output.

- **Risk scoring**  
  - Base + deltas; bands 0–100.

- **Conventions & rule base**  
  - Makefile (lint, format, test, ci); RULE.md; GOVERNANCE/; **Rule register:** `docs/rule_register.csv` validated in CI.

- **Reproducibility (reproduce-run)**  
  - Get correlation_id; run `aml reproduce-run <id> [out]`; bundle contents.

- **Project layout**  
  - Tree (config, scripts, src, tests, Makefile, pyproject.toml, README, RUNBOOK, .env.example).

- **Linting & tests**  
  - make format, lint, test, ci.

- **Sanity checks (after clone + poetry install)**  
  - Lint, test, pipeline, API curl.

- **Threat model notes**  
  - Secrets, validation, logging, scope.

- **License**  
  - Internal/portfolio.

- **Why this repo is different (new section)**  
  - CI proof (`docs/MAKE_CI_PROOF.md`, `./scripts/ci.sh`).  
  - Rule register (`docs/rule_register.csv`) validated in CI.  
  - Reproduce bundle (`aml reproduce-run`) for full run export.  
  - Audit chain (AuditLog hash chain; tests in test_audit_chain).  
  - Adversarial and determinism tests (scenario_library.md; test_adversarial_evasion, test_determinism).

---

## 2. Screenshot / GIF Plan

| Asset | What to show | Data to use |
|-------|----------------|-------------|
| **Screenshot: Alerts table** | Streamlit dashboard Alerts tab — paginated table with rule_id, severity, status, disposition | After `./scripts/demo.sh`: use default seed alerts |
| **Screenshot: SAR report preview** | Dashboard “SAR Report” tab — table of latest sar_*.json preview | Same run; reports/ populated by demo |
| **Screenshot: API docs** | Browser at http://localhost:8000/docs — OpenAPI with /alerts, /cases, /score, etc. | Same run |
| **GIF (optional): Demo flow** | Terminal: Docker up → demo.sh → “Demo summary” with ALERT_ID, CORRELATION_ID, CASE_ID; then browser tabs dashboard + API docs | Synthetic data from demo.sh; no PII |

**Where to place:** README (one screenshot under Quick start or “Dashboard”); optionally a `docs/screenshots/` or `docs/images/` folder referenced from README and GITHUB_POSITIONING.

**What data:** Only synthetic/dev data; no real PII or credentials.

---

## 3. Demo Script Narrative

**What to run:**  
1. Ensure Docker is running.  
2. From repo root: `./scripts/demo.sh`.  
3. Wait for “Demo summary” (ALERT_ID, CORRELATION_ID, CASE_ID, paths to SAR and reproduce bundle).  
4. Open http://localhost:8501 (dashboard) and http://localhost:8000/docs (API).  
5. Optional: run `aml reproduce-run <CORRELATION_ID> out.json` (inside container or local with same DB) and inspect `out.json`.

**What it proves:**  
- One-command deploy and seed (Docker Compose + migrations + synthetic data + ingest + build-network + run-rules + reports).  
- API is up (alerts, cases).  
- Mutations work (PATCH alert, POST case) with API key.  
- Reproduce-run produces a JSON bundle for the run.  
- Dashboard shows alerts, cases, and SAR preview.  
- Stopping: `./scripts/demo.sh --down`.

---

## 4. Badges Plan

| Badge | Target | Note |
|-------|--------|------|
| **CI** | “CI: make ci” or link to GitHub Actions workflow | When repo has Actions: badge from workflow (e.g. “CI” passing). Today: text badge “CI: ./scripts/ci.sh” or “CI: make ci” linking to README § Run CI locally. |
| **Coverage** | Optional: pytest-cov; badge from Actions or shield.io | Add if/when pytest-cov is in use and reported. |
| **License** | Standard “License: Internal” or “License” badge | No change if internal. |

**Minimal addition:** In README near the top, add a line:  
`CI: \`make ci\` (see [Run CI locally](#run-ci-locally))`  
or, when GitHub Actions exists:  
`[![CI](https://github.com/<org>/<repo>/actions/workflows/ci.yml/badge.svg)](https://github.com/<org>/<repo>/actions)`

---

## 5. “Why This Is Different” Section (Verifiable Artifacts)

Suggested wording for README:

**Why this repo is different**

- **CI proof** — Single command `./scripts/ci.sh` runs lint and tests; result documented in `docs/MAKE_CI_PROOF.md`.  
- **Rule register** — Every detection rule is listed in `docs/rule_register.csv` (scenario_id, severity, owner); validated in CI.  
- **Reproduce bundle** — For any run, `aml reproduce-run <correlation_id>` exports a JSON bundle (audit logs, alerts, cases, network) for audits and “why was this flagged?”.  
- **Audit chain** — AuditLog entries form a hash chain; tampering is detectable (`tests/test_audit_chain.py`).  
- **Adversarial and determinism tests** — Typologies in `docs/scenario_library.md` are covered by tests; same input → same alerts; chunk-size invariance and resume without duplicates.

All of the above are backed by files and commands in this repo; no unsupported claims.

---

*This package aligns with `docs/BENCHMARK_TOP_PROJECTS.md` and `docs/BENCHMARK_FINDINGS_AND_ACTIONS.md`.*
