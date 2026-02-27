# AML Transaction Monitoring Engine

Production-grade AML (Anti-Money Laundering) transaction monitoring MVP for a fintech security portfolio. Ingests transactions (CSV/JSONL), runs rule-based detection and risk scoring, produces alerts and SAR-like reports, with a FastAPI and CLI interface.

## Dashboard (Screenshots)

![Overview](docs/assets/overview.png?v=2)
![Alerts](docs/assets/alerts.png?v=2)
![Network](docs/assets/network.png?v=2)

## Portfolio Overview

**What problem it solves:** Transaction monitoring for AML: ingest transactions, run configurable detection rules (high-value, sanctions keywords, high-risk country, rapid velocity, network ring), score risk, produce alerts and SAR-style reports. Case workflow (create case from alerts, update status, add notes) and full audit traceability so you can answer “why was transaction X flagged?” and reproduce any run.

**Key differentiators:** Idempotent ingest (canonical `external_id`); correlation_id traceability on every run and alert; case lifecycle (NEW → INVESTIGATING → ESCALATED → CLOSED) with validated transitions; network relationship edges and NetworkRingIndicator rule; governance pack (MRM, tuning, data quality, [AUDIT_PLAYBOOK](docs/GOVERNANCE/AUDIT_PLAYBOOK.md)); `reproduce-run` CLI to export a full JSON bundle (audit logs, alerts, cases, network) by correlation_id; API-key auth for mutations with actor binding (no spoofed X-Actor); keys have scopes (read_only / read_write); mutations require read_write.

**Architecture snapshot:** CSV/JSONL → ingest → SQLite/Postgres (Customer, Account, Transaction, Alert, AuditLog, Case, RelationshipEdge); rules engine + scoring → alerts; FastAPI (GET /alerts, /cases, /transactions, /health, /network/account/{account_id}; PATCH/POST with X-API-Key); CLI (ingest, run-rules, build-network, generate-reports, reproduce-run); Alembic for Postgres migrations.

**Quickstart (CI + Docker + demo):** `make ci` → start Docker Desktop → `docker compose up -d --build` → `./scripts/demo.sh` (see [RUNBOOK § Demo](RUNBOOK.md#demo)). Then open **http://localhost:8501** for the dashboard and **http://localhost:8000/docs** for the API. Governance and conventions: [docs/GOVERNANCE/](docs/GOVERNANCE/), [docs/RULE.md](docs/RULE.md).

## Requirements

- **Python 3.11+**
- **macOS or Linux** (commands are cross-platform)

## Quick Start

```bash
# Clone and enter project
cd "AML Transaction Monitoring Engine Project"

# Install dependencies (Poetry). If you use uv: uv sync
poetry lock
poetry install

# Generate synthetic data
poetry run python scripts/generate_synthetic_data.py

# Ingest into SQLite
poetry run aml ingest data/synthetic/transactions.csv

# Run detection rules
poetry run aml run-rules

# Generate SAR reports (JSON + CSV)
poetry run aml generate-reports

# Start API (optional). Use PORT=8001 to avoid port collisions; see RUNBOOK Manual Verification.
make serve
# Or: PORT=8001 make serve  → http://127.0.0.1:8001/alerts
```

## Exact commands (copy-paste)

```bash
# From project root (macOS/Linux)
cd "AML Transaction Monitoring Engine Project"
poetry install
poetry run python scripts/generate_synthetic_data.py
poetry run aml ingest data/synthetic/transactions.csv
poetry run aml run-rules
poetry run aml generate-reports
# Optional: poetry run aml serve-api
# Optional stream: poetry run aml simulate-stream data/synthetic/transactions.csv --delay 0.5
```

## Run CI locally

Run lint and tests from your Cursor terminal with one command.

**Prerequisites:** Python 3.11+ and [Poetry](https://python-poetry.org/docs/#installation).

**Command (from repo root):**

```bash
chmod +x scripts/ci.sh   # once, to make the script executable
./scripts/ci.sh
```

The script ensures Poetry is available, runs `poetry install`, then `poetry run make ci`. It exits non-zero on failure.

**Troubleshooting:** If you see `Poetry is not installed or not on PATH`, the script prints the official install command. Install Poetry (e.g. `curl -sSL https://install.python-poetry.org | python3 -`), add it to PATH (e.g. `$HOME/.local/bin`), and run `./scripts/ci.sh` again.

## Terminal setup (Cursor / VS Code)

So that **your** terminal in this workspace is ready for `make ci` and `poetry`:

1. **New terminals open in the project root** — Workspace setting is in `.vscode/settings.json` (`terminal.integrated.cwd`).
2. **One-time per terminal (or per session):**  
   ```bash
   chmod +x scripts/setup_terminal.sh   # once
   source scripts/setup_terminal.sh      # installs deps, then runs poetry shell
   make ci
   ```  
   Or without activating the shell: `poetry run make ci`.

The AI agent in Cursor runs commands in a **separate** environment and cannot use your terminal. To have the agent work with real CI results, run `make ci` in your terminal and paste the output into the chat (or into `docs/MAKE_CI_OUTPUT_AFTER_RULES_VERSION.md`).

## Architecture (ASCII)

```
                    +------------------+
                    |  CSV / JSONL     |
                    |  (files)         |
                    +--------+---------+
                             |
                             v
    +----------------+  ingest   +----------------+
    |  Typer CLI     |---------->|  SQLite        |
    |  ingest,       |           |  (SQLAlchemy   |
    |  run-rules,    |           |   2.x)         |
    |  generate-     |<----------+  Customer,     |
    |  reports,      |  session  |  Account,      |
    |  serve-api,    |           |  Transaction,  |
    |  simulate-     |           |  Alert,        |
    |  stream        |           |  AuditLog      |
    +--------+-------+           +--------+-------+
             |                            |
             | run-rules                  |
             v                            v
    +----------------+           +----------------+
    |  Rules engine  |           |  Reporting      |
    |  (HighValue,   |           |  SAR JSON/CSV   |
    |   RapidVelocity|           +----------------+
    |   GeoMismatch, |
    |   Structuring, |
    |   Sanctions,   |
    |   HighRiskCtry)|           +----------------+
    +--------+-------+           |  FastAPI        |
             |                  |  /score,        |
             v                  |  /alerts,       |
    +----------------+          |  /transactions  |
    |  Scoring       |          +----------------+
    |  base + deltas |
    |  band 0-100    |
    +----------------+
```

## Data Flow

1. **Ingest**: CSV or JSONL → parsed → `Customer`/`Account` (upsert by `iban_or_acct`) → `Transaction` rows.
2. **Run rules**: For each transaction, build `RuleContext`, run all enabled rules, collect `RuleResult`s → create `Alert` rows and set `Transaction.risk_score` via scoring.
3. **Reports**: Query alerts + transaction fields → write JSON and CSV under `config.reporting.output_dir`.
4. **API**: `POST /score` scores one transaction (stateless rules or full run if account exists); `GET /alerts` and `GET /transactions/{id}` read from DB.

## Commands Reference

| Command | Description |
|--------|-------------|
| `poetry run aml ingest PATH` | Ingest CSV or JSONL file; column mapping inferred from headers or loaded from a `.schema.json` file next to the data (see **Adaptive ingest** below) |
| `poetry run aml discover PATH [--save]` | Infer column mapping from file headers and optionally save it to `PATH.schema.json` so future ingests reuse it (engine learns from your data without code changes) |
| `poetry run aml train` | Derive rule thresholds from ingested data; write `config/tuned.yaml` (merged on next run) |
| `poetry run aml build-network` | Build relationship edges (required for network-ring rule) |
| `poetry run aml run-rules` | Run all rules on stored transactions |
| `poetry run aml generate-reports` | Write SAR-like JSON + CSV |
| `poetry run aml serve-api` | Start FastAPI (default port 8000) |
| `poetry run aml simulate-stream PATH` | Simulate stream: ingest file in batches with delay |
| `poetry run aml reproduce-run CORRELATION_ID [OUT_PATH]` | Export run bundle (audit logs, alerts, cases, network) to JSON; see [AUDIT_PLAYBOOK](docs/GOVERNANCE/AUDIT_PLAYBOOK.md) |
| `streamlit run scripts/dashboard.py` or `make dashboard` | Start the **dashboard** (alerts, cases, SAR report preview) in the browser; see [docs/DASHBOARD.md](docs/DASHBOARD.md). |

Options (common): `-c` / `--config` to pass a YAML config path.

**Adaptive ingest (learn from your data):** The engine does not require fixed column names. It infers a mapping from your CSV/JSONL headers (e.g. `timestamp` → `ts`, `account_id` → `iban_or_acct`, `risk_band` → `base_risk`). Run `aml discover PATH --save` once to infer and persist the mapping to `PATH.schema.json`; subsequent `aml ingest PATH` will load that schema so the engine adapts to your data independently. You can also use `aml ingest PATH --save-schema` to infer and save the mapping after a successful ingest.

## Configuration

- **Default**: `config/default.yaml` (SQLite).
- **Override**: `config/dev.yaml` (merged when `AML_ENV=dev`) or env vars `AML_*` (e.g. `AML_DATABASE_URL`, `AML_LOG_LEVEL`).
- **PostgreSQL** (faster run-rules): Set `AML_DATABASE_URL=postgresql://user:pass@host:5432/db`, run `alembic upgrade head`, then use the CLI as usual. See [docs/POSTGRES.md](docs/POSTGRES.md) and `docker-compose up -d` for local Postgres.
- **Tuned (train)**: After `aml train`, `config/tuned.yaml` is written and **merged automatically** on the next run (run-rules, ingest, etc.). The engine “trains itself” from ingested data: high-value and structuring thresholds from amount percentiles, rapid-velocity from per-account transaction counts in a 15‑minute window. Delete `config/tuned.yaml` to revert to default/dev only.
- Copy `.env.example` to `.env` and set overrides; never commit secrets.

## Detection Rules (Implemented)

| Rule | Description | Output |
|------|-------------|--------|
| **HighValueTransaction** | amount >= threshold (default 10,000) | severity, reason, evidence, score_delta |
| **RapidVelocity** | >= N txns from same account in T minutes | same |
| **GeoMismatch** | Unusual country spread for customer in window | same |
| **StructuringSmurfing** | Many txns just below threshold in window | same |
| **SanctionsKeywordMatch** | Counterparty name contains keyword from list | same |
| **HighRiskCountry** | Transaction country in config high-risk list | same |

## Risk Scoring

- Base risk per customer (configurable; default 10).
- Add `score_delta` per rule hit; normalize to 0–100.
- Bands: **low** (< 33), **medium** (33–65), **high** (66–100).
- Stored on `Transaction.risk_score` and reflected in alerts.

## Conventions & rule base

- **Tooling**: Lint/format/test via `make lint`, `make format`, `make test`, `make ci` (see Makefile).
- **Single source of truth**: [docs/RULE.md](docs/RULE.md) — tooling, code conventions, structure, operations. Keep changes aligned with it.
- **Governance**: [docs/GOVERNANCE/](docs/GOVERNANCE/) — MRM, tuning, data quality, and [AUDIT_PLAYBOOK.md](docs/GOVERNANCE/AUDIT_PLAYBOOK.md) for “why was txn X flagged?”

- **Rule register**: [docs/rule_register.csv](docs/rule_register.csv) lists every detection rule (scenario_id, severity, owner); it is validated in CI via `scripts/validate_rule_register.py`.

## Reproducibility (reproduce-run)

To reproduce a run (e.g. for audits or “why was this flagged?”):

1. **Get a correlation_id** — From the API: `GET /alerts?limit=1` and read `correlation_id` from any alert; or from `audit_logs` after a CLI/API run (e.g. `run_rules` writes one per batch).
2. **Produce a JSON bundle** — `poetry run aml reproduce-run <correlation_id> [output_path]`. Example: `poetry run aml reproduce-run 057696d5-6833-4ede-a87a-c2cf5b25adda reproduce_bundle.json`. If `output_path` is omitted, the bundle is written to `reproduce_<correlation_id>.json` in the current directory. The bundle contains `metadata`, `config` (config_hashes, rules/engine versions, `resolved`), `audit_logs`, `alerts`, `cases`, `network`, and `transactions` (for alerted transactions) for that run. The command writes an AuditLog entry (`action=reproduce_run`) with the output path.

## Project Layout

```
.
├── config/
│   ├── default.yaml
│   └── dev.yaml
├── data/                 # Created at runtime (DB, synthetic, reports)
├── scripts/
│   └── generate_synthetic_data.py
├── src/
│   └── aml_monitoring/
│       ├── __init__.py
│       ├── api.py
│       ├── cli.py
│       ├── config.py
│       ├── db.py
│       ├── logging_config.py
│       ├── models.py
│       ├── reporting.py
│       ├── run_rules.py
│       ├── schemas.py
│       ├── scoring.py
│       ├── simulate.py
│       ├── ingest/
│       │   ├── csv_ingest.py
│       │   └── jsonl_ingest.py
│       └── rules/
│           ├── base.py
│           ├── high_value.py
│           ├── rapid_velocity.py
│           ├── geo_mismatch.py
│           ├── structuring_smurfing.py
│           ├── sanctions_keyword.py
│           └── high_risk_country.py
├── tests/
├── Makefile
├── pyproject.toml
├── README.md
├── RUNBOOK.md
└── .env.example
```

## Linting & Tests

All Makefile targets run via Poetry's venv (`poetry run ...`); ruff, black, mypy, and pytest do not need to be on your system PATH.

```bash
# Format (black + ruff --fix)
make format

# Lint (ruff + black --check + mypy)
make lint

# Test
make test

# CI: lint then test
make ci
```

## Sanity checks (after clone + poetry install)

```bash
# 1) Lint and test
make lint
make test

# 2) Generate data, ingest, run rules, reports
make synthetic
make ingest
make run-rules
make reports

# 3) Start API and hit endpoints
poetry run aml serve-api &
sleep 2
curl -s http://localhost:8000/alerts
curl -s -X POST http://localhost:8000/score -H "Content-Type: application/json" -d '{"transaction":{"account_id":1,"ts":"2025-01-01T12:00:00","amount":50000,"currency":"USD","country":"USA"}}'
# Stop: kill %1
```

## Threat Model Notes

- **Secrets**: No API keys or passwords in repo; use `.env` and env vars.
- **Input validation**: All API inputs validated with Pydantic; file ingest validates types and ranges.
- **Logging**: No sensitive fields logged (redaction for password/token-like keys).
- **Scope**: Local-only MVP; no external paid services; SQLite for single-node use.

## License

Internal/portfolio use.
