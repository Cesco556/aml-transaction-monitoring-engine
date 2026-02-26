# Audit Playbook: “Why was transaction X flagged?”

This playbook describes exactly how to answer “Why was transaction X flagged?” using this repo’s data: **config_hash**, **correlation_id**, **audit logs**, **evidence_fields**, and **cases/notes**.

## 1. Identify the alert(s) for the transaction

- **By transaction ID:** Use **GET /transactions/{transaction_id}**; the response includes `alerts` for that transaction. Each alert has `id`, `rule_id`, `severity`, `reason`, `evidence_fields`, `config_hash`, `correlation_id`, `status`, `disposition`.
- **By correlation_id (run):** Use **GET /alerts?correlation_id=<uuid>** to list all alerts from a specific rule run. Match the transaction’s alert(s) by `transaction_id` in the list or via the transaction endpoint above.

## 2. Why it was flagged (rule and evidence)

- **rule_id:** Identifies the rule that fired (e.g. HighValueTransaction, SanctionsKeywordMatch, HighRiskCountry, RapidVelocity, NetworkRingIndicator).
- **reason:** Human-readable explanation from the rule.
- **evidence_fields:** JSON with rule-specific evidence (e.g. threshold exceeded, keyword matched, country code, count/window for velocity, or network metrics). Use this to explain “what the rule saw.”
- **config_hash:** SHA256 of the resolved config at run time. Ensures you can tie the outcome to the exact config (thresholds, toggles) used.

## 3. Which run produced it (correlation_id)

- **correlation_id** on the alert (and in AuditLog for that run) identifies the **run** (e.g. a single `aml run-rules` invocation or a batch job). Use it to:
  - List all alerts from that run: **GET /alerts?correlation_id=<uuid>**.
  - Reproduce the run: **`aml reproduce-run --correlation-id <uuid> [--out <path>]`** to get a JSON bundle with audit_logs, alerts, cases, network summary, and config hashes for that run.

## 4. Audit trail (audit_logs)

- **audit_logs** table: Filter by `correlation_id` to get all actions for that run (e.g. `run_rules` with `processed`/`alerts_created`, ingest batches, report generation). For **disposition_update**, look up by `entity_type='alert'` and `entity_id=<alert_id>` to see who closed it and when (actor, details_json with old/new status and disposition).
- **reproduce-run** bundle includes `audit_logs` for the given correlation_id, ordered by `ts`, so you can trace the run end-to-end.

## 5. Cases and notes

- If the alert was attached to a **case**, the case record and its **notes** document investigation and rationale. Cases have `correlation_id`; case notes may have their own `correlation_id` for the request that added them. The **reproduce-run** bundle includes **cases** (with items and notes) for the run’s correlation_id where applicable.
- Use case **status** and **notes** to answer “how was this followed up?” (e.g. closed as false positive, escalated, SAR filed).

## 6. Quick checklist

1. Get **transaction_id** (e.g. from system of record or search).
2. Call **GET /transactions/{transaction_id}** to get **alerts** for that transaction.
3. For each alert: note **rule_id**, **reason**, **evidence_fields**, **config_hash**, **correlation_id**.
4. Optionally call **GET /alerts?correlation_id=<uuid>** to see the full run.
5. Run **`aml reproduce-run --correlation-id <uuid> --out run.json`** to get the full bundle (audit_logs, alerts, cases, network) for that run.
6. In the bundle or DB, check **audit_logs** for `disposition_update` on that alert and **cases** (and notes) referencing the alert to complete the story.
