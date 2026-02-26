# Scenario Library — Typologies and Expected Rules

Mapping of typology scenarios to detection rules or OUT_OF_SCOPE. Used for adversarial tests and governance.

| scenario_id | description | expected_rule | notes |
|-------------|-------------|---------------|-------|
| structuring_just_under | Multiple txns just below reporting threshold in short window | StructuringSmurfing | threshold_amount, min_transactions, window_minutes in config |
| smurfing_velocity | Many transactions from same account in short time | RapidVelocity | min_transactions, window_minutes |
| high_value_single | Single transaction above threshold | HighValueTransaction | threshold_amount |
| sanctions_keyword | Counterparty name contains sanctions keyword | SanctionsKeywordMatch | keywords list |
| high_risk_country | Transaction country in high-risk list | HighRiskCountry | countries list |
| geo_mismatch | Same customer, multiple countries in window | GeoMismatch | max_countries_in_window |
| network_ring | Accounts sharing counterparties (ring) | NetworkRingIndicator | requires build_network first |
| round_trip | A→B→A same amount | OUT_OF_SCOPE | No dedicated rule; could add in future |
| name_variation_typo | Typo in counterparty to evade keyword match | SanctionsKeywordMatch or OUT_OF_SCOPE | Substring match may miss typos |
| payroll_batch | Regular payroll-like batches | OUT_OF_SCOPE or suppression | False positive trap; no suppression yet |
| rent_regular | Regular rent payment | OUT_OF_SCOPE | False positive trap |

## Adversarial test coverage

- **Dirty data (ingest):** malformed ts, invalid amount, missing_iban → reject_reasons in audit.
- **Evasion:** structuring_just_under, smurfing_velocity, network_ring → at least one rule fires or OUT_OF_SCOPE.
- **False positive:** payroll_batch, rent_regular → document OUT_OF_SCOPE or add suppression.

## Determinism

- Same input (CSV + config) + same seed → same set of (external_id, rule_id).
- Chunk size change (chunk_size=0 vs chunk_size=2) → same alert set.
- Resume after checkpoint → no duplicate alerts, no skipped transactions.
