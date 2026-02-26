# Architecture & Plan

## 1) Plan

- **Ingest**: CSV/JSONL → parse → upsert Customer/Account by `iban_or_acct` → insert Transaction. Uses standard `csv` and `json`; batch commits via `session_scope`.
- **Rules engine**: Config-driven list of rules (HighValue, RapidVelocity, GeoMismatch, StructuringSmurfing, SanctionsKeyword, HighRiskCountry). Each rule receives `RuleContext` (transaction + session) and returns `list[RuleResult]` (rule_id, severity, reason, evidence_fields, score_delta).
- **Scoring**: Base risk (per customer) + sum of rule score_deltas → normalized 0–100; bands low/medium/high. Persisted on `Transaction.risk_score`.
- **Alerts**: One `Alert` row per rule hit; linked to transaction.
- **Reporting**: Query alerts + transaction fields → JSON (full) + CSV (tabular) under `reporting.output_dir`.
- **API**: FastAPI with `/score` (single transaction), `/alerts`, `/transactions/{id}`. Lifespan initializes DB from config.
- **CLI**: Typer commands `ingest`, `run-rules`, `generate-reports`, `serve-api`, `simulate-stream`. Each that touches DB calls `_ensure_db(config)` (init_db + logging).
- **Config**: YAML (`config/default.yaml`, optional `dev.yaml`), env overrides `AML_*`, no secrets in repo.
- **Audit**: `AuditLog` table; run_rules writes a batch entry. Logging redacts secret-like keys.

## 2) Commands

From project root (macOS/Linux):

```bash
poetry lock
poetry install
poetry run python scripts/generate_synthetic_data.py
poetry run aml ingest data/synthetic/transactions.csv
poetry run aml run-rules
poetry run aml generate-reports
poetry run aml serve-api
# Optional: poetry run aml simulate-stream data/synthetic/transactions.csv --delay 0.5
```

Lint/test:

```bash
make format
make lint
make test
```

## 3) File tree

```
.
├── config/
│   ├── default.yaml
│   └── dev.yaml
├── data/                          # Created at runtime
├── docs/
│   └── ARCHITECTURE.md
├── scripts/
│   └── generate_synthetic_data.py
├── src/
│   └── aml_monitoring/
│       ├── __init__.py
│       ├── api.py
│       ├── cli.py
│       ├── config.py
│       ├── db.py
│       ├── logging.py
│       ├── logging_config.py
│       ├── models.py
│       ├── reporting.py
│       ├── run_rules.py
│       ├── schemas.py
│       ├── scoring.py
│       ├── simulate.py
│       ├── ingest/
│       │   ├── __init__.py
│       │   ├── csv_ingest.py
│       │   └── jsonl_ingest.py
│       └── rules/
│           ├── __init__.py
│           ├── base.py
│           ├── high_value.py
│           ├── rapid_velocity.py
│           ├── geo_mismatch.py
│           ├── structuring_smurfing.py
│           ├── sanctions_keyword.py
│           └── high_risk_country.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_rules.py
│   ├── test_scoring.py
│   ├── test_schemas.py
│   ├── test_api.py
│   └── test_integration.py
├── .env.example
├── .pre-commit-config.yaml
├── Makefile
├── pyproject.toml
├── README.md
├── requirements.txt
└── RUNBOOK.md
```

## 4) Sanity checks

Run after a clean clone:

1. `make lint` then `make test`
2. `make synthetic` → `make ingest` → `make run-rules` → `make reports` → inspect `reports/`
3. `poetry run aml serve-api` → `curl http://localhost:8000/alerts` and `POST /score` with a JSON body

## 5) Proofread & fix (applied)

- **config.py**: Use `pathlib.Path` (not `path` package).
- **csv_ingest.py**: Fix `customer_name` default (strip and fallback to `"Unknown"`).
- **geo_mismatch.py**: Fix distinct-countries query; remove unused `distinct` import.
- **run_rules.py**: Type `all_hits` as `list[RuleResult]`; import `RuleResult`; remove unused `Customer` import.
- **reporting.py**: Remove unused `SARReportRecord` import; always write CSV (header even when no records).
- **api.py**: Consolidate `RuleResult` import; use single import block for schemas.
- **tests/test_schemas.py**: Use `pytest.raises(ValidationError)` for invalid amount.
- **tests/test_integration.py**: Use single `integration_config` fixture with file-based SQLite so ingest and run_rules share the same DB; fix `test_report_generation` to use same fixture and `tmp_path`.
- **logging**: Add `logging.py` re-export for deliverable list.

All commands are cross-platform (macOS/Linux). No secrets in repo; input validation via Pydantic and ingest parsing.
