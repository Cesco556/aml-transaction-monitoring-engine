# Data Quality

This document describes input validations, duplicate handling, timestamp/currency normalization, and logging/PII for the AML Transaction Monitoring Engine.

## Input validations (schema and required fields)

- **CSV/JSONL ingest:** Rows must include the columns/keys expected by the ingest pipeline (e.g. `customer_name`, `country`, `iban_or_acct`, `ts`, `amount`, `currency`, `merchant`, `counterparty`, `country_txn`, `channel`, `direction`, `base_risk`). Missing or invalid fields can cause row skip or default values; see ingest code and schemas.
- **API /score:** Request body must match `ScoreRequest` schema (transaction object with required fields). Invalid payloads return 4xx.
- **API mutations (PATCH alert, POST/PATCH case, etc.):** Validated by Pydantic; invalid status/disposition or body return 4xx. No schema validation on raw CSV beyond what the ingest layer enforces.

## Duplicate handling (external_id)

- **Idempotency:** Each transaction row is canonicalized (UTC timestamp, 2-decimal amount, uppercase currency, lowercased/stripped counterparty and direction) and hashed to an **external_id**. If the same external_id is seen again (same file or re-ingest), the row is **skipped** (no new transaction row). Within a batch, `seen_in_batch` prevents duplicate inserts for the same logical row.
- **Re-ingest:** Safe to re-run ingest on the same file; only new logical transactions are inserted. Use this for reprocessing after schema or rule changes if you re-export from source.

## Timestamp and currency normalization

- **Timestamps:** Stored in UTC; ingest canonicalizes to UTC. Use `datetime.now(UTC)` and avoid `utcnow()` in code. ISO format with Z or +00:00 is expected in inputs where applicable.
- **Currency:** Stored as 3-letter (e.g. USD); ingest normalizes to uppercase. Amounts are stored as float; rounding to 2 decimals for external_id consistency.
- **Amounts:** Decimal precision in hashing uses 2 decimal places for canonical external_id; rule logic uses float comparisons (e.g. high_value threshold). Invalid non-empty string amounts are rejected (parse_error) rather than coerced to 0.0.

## Logging and PII

- **Logging:** Configurable via `AML_LOG_LEVEL`; structure in `logging_config`. **No PII** (e.g. customer names, full IBANs) should be logged in plain text; redact in logging if needed (see logging_config).
- **Audit details:** AuditLog `details_json` holds counts, IDs, config_hash, and entity identifiers—**no raw PII**. Ingest batches record `rows_rejected` and `reject_reasons` (capped) in `details_json` when rows are skipped (e.g. missing_iban, parse_error). Evidence in alerts (e.g. `evidence_fields`) may contain IDs or aggregated data; avoid putting full names or account numbers in rule evidence if not required.
- **Reports:** SAR-style reports may include transaction and alert data; control access and retention per policy. CSV/JSON output paths are configurable.
