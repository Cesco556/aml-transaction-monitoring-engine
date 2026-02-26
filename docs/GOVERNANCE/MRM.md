# Model and Rule Governance (SR 11-7 style)

This document describes governance of the AML Transaction Monitoring Engine’s **rule engine**: intended use, limitations, validation, monitoring, and change control. It is aligned with SR 11-7–style model risk management adapted to deterministic rule-based detection (no ML models).

## Intended use

- **Scope:** Transaction monitoring for AML: ingest transactions (CSV/JSONL), run configurable rules (e.g. HighValueTransaction, SanctionsKeywordMatch, HighRiskCountry, RapidVelocity, NetworkRingIndicator), score risk, produce alerts and SAR-style reports.
- **Users:** Ops/analysts (CLI, API) and downstream reporting; not for real-time payment blocking without additional controls.
- **Inputs:** Structured transaction records with required fields (see DATA_QUALITY.md); config YAML for rule toggles and thresholds.

## Limitations

- Rules are **deterministic and threshold-based**. They do not detect novel patterns beyond configured logic; tuning is required to balance false positives vs. coverage.
- **No entity resolution** across sources; duplicate/canonical handling is via `external_id` hashing only.
- **Network rule** (NetworkRingIndicator) depends on a prior `build-network` run and relationship_edges; stale edges affect results.
- **Config and code** must be versioned together; `config_hash`, `rules_version`, and `engine_version` on alerts/transactions support reproducibility, not automatic drift detection.

## Validation approach

- **Unit tests:** Rule logic (e.g. thresholds, keyword match, country list) covered in `tests/test_rules.py`; scoring in `tests/test_scoring.py`.
- **Integration tests:** Full pipeline (ingest → run-rules → reports) in `tests/test_integration.py`; idempotency and audit in `tests/test_idempotency.py`, `tests/test_api.py`.
- **Reproducibility:** `aml reproduce-run --correlation-id <uuid>` produces a JSON bundle (audit_logs, alerts, cases, network, transactions for alerted txns, config.resolved) for a given run; use for “why was this run produced?” and regulator/audit requests.
- **No backtesting framework** in-repo; threshold choices are validated by disposition feedback and manual review (see TUNING.md).

## Monitoring plan

- **Audit logs:** Every ingest batch, run_rules, report generation, and key API mutations write to `audit_logs` with `correlation_id`, `actor`, `action`, `entity_type`, `entity_id`, `details_json`.
- **Alert/case lifecycle:** Alerts have `status` and `disposition`; cases have status transitions; all changes audited. Use disposition counts and run_rules `alerts_created` / `processed` in details_json to track volume and tuning impact.
- **Operational:** Log level via config/env (`AML_LOG_LEVEL`); no PII in audit details (see DATA_QUALITY.md). Monitor for DB errors, failed ingest rows, and API 401s on protected endpoints.

## Change control

- **Rule logic or engine:** `RULES_VERSION` is set from env `AML_RULES_VERSION` or git describe (see `aml_monitoring/__init__.py`); bump `ENGINE_VERSION` in code or set `AML_RULES_VERSION` for releases. Document in release notes; run full test suite and, if needed, `reproduce-run` for a sample correlation_id before/after.
- **Config (thresholds, toggles):** Track in version control; `config_hash` on alerts/transactions ties outputs to a specific resolved config for reproducibility.
- **Schema/DB:** Alembic migrations for Postgres; SQLite uses app-driven schema with optional `AML_ALLOW_SCHEMA_UPGRADE` for dev. No ad-hoc schema changes without migration or doc update.
