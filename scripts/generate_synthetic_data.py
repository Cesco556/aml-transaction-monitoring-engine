#!/usr/bin/env python3
"""Generate synthetic transaction data (CSV and JSONL) for testing AML rules."""

from __future__ import annotations

import csv
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path


def main() -> None:
    out_dir = Path("data/synthetic")
    out_dir.mkdir(parents=True, exist_ok=True)
    random.seed(42)

    customers = [
        ("Alice Corp", "USA", "US123456789"),
        ("Bob Ltd", "GBR", "GB98MIDL12345678901234"),
        ("Carol Inc", "FRA", "FR7630006000011234567890189"),
        ("Dave LLC", "DEU", "DE89370400440532013000"),
        ("Eve SARL", "IR", "IR123456789"),  # high-risk country
    ]
    keywords_ok = ["Acme", "Global", "Trade", "Pay"]
    keywords_sanctions = ["sanctioned entity", "OFAC list", "blocked account"]

    rows: list[dict] = []
    base_ts = datetime.now(UTC) - timedelta(days=7)

    # Normal transactions
    for i in range(30):
        cust = customers[i % len(customers)]
        rows.append(
            {
                "customer_name": cust[0],
                "country": cust[1],
                "iban_or_acct": cust[2],
                "ts": (base_ts + timedelta(hours=i * 2)).strftime("%Y-%m-%dT%H:%M:%S"),
                "amount": round(random.uniform(100, 2000), 2),
                "currency": "USD",
                "merchant": random.choice(keywords_ok) + " Inc",
                "counterparty": random.choice(keywords_ok) + " Ltd",
                "country_txn": cust[1],
                "channel": "wire",
                "direction": "out",
                "base_risk": 10,
            }
        )

    # High-value
    rows.append(
        {
            "customer_name": "Alice Corp",
            "country": "USA",
            "iban_or_acct": "US123456789",
            "ts": (base_ts + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
            "amount": 50000,
            "currency": "USD",
            "merchant": "Big Payee",
            "counterparty": "Big Payee",
            "country_txn": "USA",
            "channel": "wire",
            "direction": "out",
            "base_risk": 10,
        }
    )

    # Sanctions keyword
    rows.append(
        {
            "customer_name": "Bob Ltd",
            "country": "GBR",
            "iban_or_acct": "GB98MIDL12345678901234",
            "ts": (base_ts + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
            "amount": 1000,
            "currency": "USD",
            "merchant": keywords_sanctions[0],
            "counterparty": keywords_sanctions[0],
            "country_txn": "GBR",
            "channel": "wire",
            "direction": "out",
            "base_risk": 10,
        }
    )

    # Rapid velocity: same account, 6 txns in 10 minutes
    t0 = base_ts + timedelta(days=3)
    for j in range(6):
        rows.append(
            {
                "customer_name": "Carol Inc",
                "country": "FRA",
                "iban_or_acct": "FR7630006000011234567890189",
                "ts": (t0 + timedelta(minutes=j * 2)).strftime("%Y-%m-%dT%H:%M:%S"),
                "amount": 500,
                "currency": "EUR",
                "merchant": "Retail",
                "counterparty": "Retail",
                "country_txn": "FRA",
                "channel": "card",
                "direction": "out",
                "base_risk": 10,
            }
        )

    # Structuring: just below 10k
    t1 = base_ts + timedelta(days=4)
    for _ in range(4):
        rows.append(
            {
                "customer_name": "Dave LLC",
                "country": "DEU",
                "iban_or_acct": "DE89370400440532013000",
                "ts": (t1 + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S"),
                "amount": 9200,
                "currency": "USD",
                "merchant": "Split Pay",
                "counterparty": "Split Pay",
                "country_txn": "DEU",
                "channel": "wire",
                "direction": "out",
                "base_risk": 10,
            }
        )

    # High-risk country (Eve SARL already has country IR)
    rows.append(
        {
            "customer_name": "Eve SARL",
            "country": "IR",
            "iban_or_acct": "IR123456789",
            "ts": (base_ts + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S"),
            "amount": 3000,
            "currency": "USD",
            "merchant": "Local",
            "counterparty": "Local",
            "country_txn": "IR",
            "channel": "wire",
            "direction": "out",
            "base_risk": 15,
        }
    )

    csv_path = out_dir / "transactions.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "customer_name",
                "country",
                "iban_or_acct",
                "ts",
                "amount",
                "currency",
                "merchant",
                "counterparty",
                "country_txn",
                "channel",
                "direction",
                "base_risk",
            ],
        )
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {csv_path}")

    jsonl_path = out_dir / "transactions.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"Wrote {len(rows)} lines to {jsonl_path}")


if __name__ == "__main__":
    main()
