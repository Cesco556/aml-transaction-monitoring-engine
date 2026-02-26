# Implementation Changelog Plan (pre-code)

## P0.2 Config placeholder validation (XX/YY)
- **config.py**: Add `validate_high_risk_country(config)`; call after merge in `get_config`; raise ValueError if countries contains "XX" or "YY".
- **config/default.yaml**: Keep XX/YY with comment (validation will fail unless overridden by dev/tuned).
- **tests/test_config.py**: Add test_config_rejects_placeholder_xx_yy, test_config_allows_valid_high_risk_countries.

## P0.3 Chunked + resumable run_rules
- **config/default.yaml**: Add `run_rules.chunk_size` (e.g. 5000).
- **run_rules.py**: Add chunk_size from config; loop by `Transaction.id` chunks; write last_processed_id, chunk_index to AuditLog details; add `resume_from_correlation_id` param and read last_processed_id from latest run_rules audit for that correlation_id; process from last_processed_id+1.
- **cli.py**: run_rules_cmd add --resume and optional --correlation-id; pass to run_rules.
- **tests/test_run_rules.py** (new): test_chunk_sizes_produce_identical_alerts, test_resume_no_duplicates_no_skips.

## P0.4 SAR timeliness in reporting
- **reporting.py**: Add Alert.created_at, Alert.updated_at to select; add created_at, updated_at, hours_to_disposition to each record; include in JSON (and optionally CSV).
- **tests/test_reporting.py** (new) or test_integration: test_sar_report_includes_timeliness_and_hours_to_disposition.

## P0.5 /health endpoint
- **api.py**: Add GET /health; return 200, body with engine_version, rules_version, db_status (ping).
- **tests/test_api.py**: test_health_returns_200_and_version.

## P1.4 Reproduce bundle: transactions + resolved config
- **reproduce.py**: Collect distinct transaction_ids from alerts; fetch Transaction rows; add bundle["transactions"] with serialized payload (id, account_id, ts, amount, currency, etc.); add bundle["config"]["resolved"] = get_config(config_path) (full dict).
- **tests/test_reproduce.py** (new): test_bundle_contains_transactions, test_every_alert_transaction_id_in_transactions, test_bundle_contains_resolved_config.

## P1.2 Per-rule version/hash on alerts
- **rules/base.py**: Add `rule_hash: str` class attribute or method returning stable hash (e.g. rule_id + module name hash).
- **rules/*.py**: Each rule set RULE_HASH or get_rule_hash(); run_rules merges into evidence_fields when creating Alert.
- **run_rules.py**: When creating Alert, add hit.evidence_fields["rule_hash"] = getattr(rule, "RULE_HASH", rule.rule_id).
- **tests/test_rules.py** or new: test_per_rule_hash_in_alert_evidence, test_rule_hash_stable.

## P1.3 Lists discipline: list_version + effective_date
- **config/default.yaml**: Add sanctions_keyword.list_version, effective_date; high_risk_country.list_version, effective_date.
- **rules/sanctions_keyword.py**: Read from config; add to evidence_fields when rule fires.
- **rules/high_risk_country.py**: Same.
- **tests/test_rules.py**: test_sanctions_evidence_has_list_version, test_high_risk_evidence_has_effective_date.

## P1.5 API key scopes/roles
- **auth.py**: Parse AML_API_KEYS with optional scope: "name:key:scope" or "name:key" (default scope "read_write"); require_scope(scope) dependency; check scope for PATCH /alerts, POST /cases (require "write" or "read_write").
- **api.py**: Use require_api_key then require_scope("write") for PATCH; cases_api same for POST.
- **tests/test_api.py**: test_read_only_key_gets_403_on_patch_alerts, test_write_key_succeeds.

## P1.6 GET /network/account/{id}
- **api.py**: Add GET /network/account/{account_id}; query RelationshipEdge where src_type=account, src_id=account_id; return edges + optional ring_signal.
- **tests/test_api.py**: test_network_account_returns_edges.

## P2.1 Audit log hash chain
- **models.py**: AuditLog add prev_hash, row_hash (String(64) nullable).
- **alembic**: New migration adding prev_hash, row_hash to audit_logs.
- **db.py**: If SQLite schema upgrade, add columns.
- **audit logging**: On each AuditLog insert, compute row_hash = hash(prev_id, action, entity_type, entity_id, ts, actor, details_json); set prev_hash from previous row; first row prev_hash = None or genesis.
- **tests/test_audit_chain.py**: test_audit_chain_verification, test_tampering_breaks_verification.

## P2.3 Scenario library + adversarial + determinism
- **docs/scenario_library.md**: Create with typology_id, description, expected_rule or OUT_OF_SCOPE.
- **tests/test_adversarial_ingest.py**: Extend test_ingest_rejects (dirty data).
- **tests/test_adversarial_evasion.py**: Structuring, smurfing, mule, round-trip, name variation fixtures and expected outcomes.
- **tests/test_adversarial_fp.py**: Payroll/rent/bills fixture; document or suppress.
- **tests/test_determinism.py**: same input twice → same (external_id, rule_id); chunk_size differs → same outputs; resume → no duplicate/skip.
- **Makefile**: Add targets test-adversarial, test-determinism, test-scenario.
