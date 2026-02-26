# Tuning: Reducing False Positives

This repo’s rules are threshold- and keyword-based. This document describes how to reduce false positives using disposition workflow, threshold tuning, sampling, and metrics.

## Disposition workflow

- **Alerts** have `status` (open/closed) and `disposition` (false_positive, escalate, sar). Use **PATCH /alerts/{id}** (with `X-API-Key`) or CLI **`aml update-alert --id <id> --status closed --disposition false_positive`** to record outcomes.
- **Cases** group related alerts/transactions; use **POST /cases**, **PATCH /cases/{id}**, **POST /cases/{id}/notes** to document investigation and close in bulk where appropriate.
- All disposition and case updates are **audited** (AuditLog); actor is from API key (mutations) or CLI `AML_ACTOR`. Use these logs to compute false-positive rates per rule or per analyst.

## Threshold tuning loop

1. **Baseline:** Run rules on a representative period; capture `correlation_id` from run_rules (or from **GET /alerts?correlation_id=...**).
2. **Review:** Disposition alerts (false_positive vs. escalate/sar). Optionally tag by rule_id in notes or external reporting.
3. **Adjust config:** In `config/default.yaml` (or dev overlay), change rule parameters, e.g.:
   - `high_value.threshold_amount`
   - `rapid_velocity.min_transactions`, `window_minutes`
   - `high_risk_country.countries`
   - `sanctions_keyword.keywords`
   - `network_ring.min_shared_counterparties`, `min_linked_accounts`
4. **Re-run and compare:** New run gets a new `config_hash`. Use **`aml reproduce-run --correlation-id <old_run>`** and compare to a new run’s bundle to see config_hash and alert counts.
5. **Version config:** Commit YAML changes; `config_hash` on alerts ties results to that config for audits.

## Sampling

- For large backlogs, prioritize by **severity**, **rule_id**, or **age**. Use **GET /alerts?limit=...&severity=high** (or filter by `correlation_id` for a specific run).
- No built-in random sampling in the API; export alerts (or use reports) and sample in a spreadsheet or external tool. Disposition results can be aggregated by rule_id to drive threshold changes.

## Metrics to track

- **Per rule_id:** Count of alerts, count closed as false_positive vs. escalate/sar; ratio (e.g. false_positive_rate).
- **Per run:** `processed` and `alerts_created` in AuditLog `action=run_rules` details_json; compare before/after threshold changes.
- **Config_hash:** Present on Alert and Transaction; use in **reproduce-run** bundle to confirm which config produced a run. Track config_hash in change control when tuning.
