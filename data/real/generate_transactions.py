#!/usr/bin/env python3
"""
generate_transactions.py
========================
Synthetic bank / fintech transaction-log generator for AML transaction-monitoring testing.

Produces a single CSV file (transactions.csv) with ~100 000 rows of realistic-looking
operational transaction data.  All names, accounts, and identifiers are fictional.

Usage:
    python generate_transactions.py          # writes transactions.csv in cwd
    python generate_transactions.py --rows 50000 --out /tmp/txns.csv

Deterministic: fixed seed (default 20260223) so the same run always reproduces the
same file.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import os
import random
import string
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

# ---------------------------------------------------------------------------
# 0. Constants & configuration
# ---------------------------------------------------------------------------

SEED = 20260223
NUM_ROWS = 100_000
NUM_ACCOUNTS_MIN = 5_000
NUM_ACCOUNTS_MAX = 12_000
START_DATE = datetime(2025, 9, 1, tzinfo=timezone.utc)
END_DATE = datetime(2025, 11, 29, tzinfo=timezone.utc)  # 90 days

CURRENCIES = ["GBP", "EUR", "USD"]
CURRENCY_WEIGHTS = [0.55, 0.25, 0.20]

TRANSACTION_TYPES = [
    "card_purchase",
    "bank_transfer",
    "cash_withdrawal",
    "cash_deposit",
    "bill_payment",
    "salary",
    "p2p_transfer",
    "merchant_payout",
]
TXN_TYPE_WEIGHTS = [0.30, 0.18, 0.08, 0.05, 0.15, 0.08, 0.12, 0.04]

CHANNELS = ["mobile_app", "web", "atm", "branch", "card_pos", "api"]
CHANNEL_BY_TXN = {
    "card_purchase":    ["card_pos", "mobile_app", "web"],
    "bank_transfer":    ["mobile_app", "web", "api", "branch"],
    "cash_withdrawal":  ["atm", "branch"],
    "cash_deposit":     ["atm", "branch"],
    "bill_payment":     ["mobile_app", "web", "api"],
    "salary":           ["api"],
    "p2p_transfer":     ["mobile_app", "web"],
    "merchant_payout":  ["api", "web"],
}

COUNTERPARTY_TYPES = ["individual", "merchant", "internal_account", "exchange", "payroll_provider"]
CPTY_BY_TXN = {
    "card_purchase":    ["merchant"],
    "bank_transfer":    ["individual", "internal_account", "exchange"],
    "cash_withdrawal":  ["internal_account"],
    "cash_deposit":     ["internal_account"],
    "bill_payment":     ["merchant"],
    "salary":           ["payroll_provider"],
    "p2p_transfer":     ["individual"],
    "merchant_payout":  ["merchant"],
}

CUSTOMER_SEGMENTS = ["retail", "sme"]
SEGMENT_WEIGHTS = [0.82, 0.18]
RISK_BANDS = ["low", "medium", "high"]
RISK_BAND_WEIGHTS = [0.70, 0.22, 0.08]

COUNTRIES = ["GB", "US", "DE", "FR", "NL", "IE", "AE", "NG", "IN", "SG", "HK", "CH", "ES", "IT", "PT"]
DOMESTIC_COUNTRY_WEIGHTS = {
    "GBP": ("GB", 0.92),
    "EUR": ("DE", 0.40),
    "USD": ("US", 0.88),
}

# Merchant Category Codes (common)
MCC_MAP = {
    "grocery":      ("5411", ["TESCO STORES", "SAINSBURYS", "ALDI STORES", "LIDL GB", "ASDA SUPERSTORE",
                              "MORRISONS", "WAITROSE", "CO-OP GROUP", "M&S FOODHALL", "OCADO"]),
    "restaurant":   ("5812", ["NANDOS", "WAGAMAMA", "PIZZA EXPRESS", "GREGGS", "PRET A MANGER",
                              "FIVE GUYS", "DISHOOM", "HONEST BURGERS", "ITSU", "LEON"]),
    "fuel":         ("5541", ["BP CONNECT", "SHELL", "ESSO TESCO", "TEXACO", "GULF PETROL",
                              "JET GARAGE", "MURCO", "HARVEST ENERGY"]),
    "clothing":     ("5651", ["PRIMARK", "NEXT RETAIL", "ZARA", "H&M", "UNIQLO",
                              "TK MAXX", "RIVER ISLAND", "MARKS SPENCER"]),
    "electronics":  ("5732", ["CURRYS", "ARGOS", "APPLE STORE", "JOHN LEWIS TECH", "SAMSUNG STORE"]),
    "subscription": ("5968", ["NETFLIX.COM", "SPOTIFY", "AMAZON PRIME", "DISNEY PLUS", "APPLE.COM/BILL",
                              "GOOGLE STORAGE", "MICROSOFT 365", "ADOBE SYSTEMS"]),
    "travel":       ("4511", ["BRITISH AIRWAYS", "EASYJET", "RYANAIR", "BOOKING.COM", "AIRBNB",
                              "TRAINLINE", "UBER TRIP", "BOLT RIDE", "NATIONAL EXPRESS"]),
    "utilities":    ("4900", ["BRITISH GAS", "EDF ENERGY", "OCTOPUS ENERGY", "THAMES WATER",
                              "BT GROUP", "SKY UK", "VIRGIN MEDIA", "THREE MOBILE"]),
    "healthcare":   ("8099", ["BOOTS PHARMACY", "LLOYDS PHARMACY", "BUPA", "DENPLAN",
                              "SPECSAVERS"]),
    "general_merch":("5999", ["AMAZON.CO.UK", "EBAY", "ASOS.COM", "ETSY.COM",
                              "IKEA", "WILKO", "HOMEBASE", "B&Q"]),
}

BILL_PAYEES = [
    "COUNCIL TAX", "HMRC SELF ASSESSMENT", "HMRC PAYE", "RENT PAYMENT",
    "MORTGAGE PYMT", "STUDENT LOAN CO", "TV LICENCE", "INSURANCE PREM",
    "CHILDCARE PYMT", "BROADBAND BILL", "GYM MEMBERSHIP", "PENSION CONTRIB",
]

SALARY_PAYERS = [
    "ACME LTD", "GLOBEX CORP", "INITECH", "HOOLI INC", "STARK INDUSTRIES",
    "WAYNE ENTERPRISES", "UMBRELLA CORP", "CYBERDYNE SYSTEMS", "WONKA INDUSTRIES",
    "APERTURE SCIENCE", "OSCORP", "LEXCORP", "WEYLAND YUTANI", "SOYLENT CORP",
    "MASSIVE DYNAMIC", "TYRELL CORP", "PIED PIPER", "DUNDER MIFFLIN",
]

FIRST_NAMES = [
    "James", "Mary", "Robert", "Jennifer", "Michael", "Linda", "David", "Sarah",
    "Richard", "Jessica", "Joseph", "Karen", "Thomas", "Nancy", "Charles", "Lisa",
    "Daniel", "Margaret", "Matthew", "Sandra", "Anthony", "Ashley", "Mark", "Dorothy",
    "Paul", "Kimberly", "Steven", "Emily", "Andrew", "Donna", "Kenneth", "Michelle",
    "George", "Carol", "Edward", "Amanda", "Brian", "Melissa", "Ronald", "Deborah",
    "Aisha", "Chinedu", "Fatima", "Raj", "Wei", "Yuki", "Hassan", "Olga",
    "Priya", "Lars", "Ingrid", "Chen", "Amara", "Boris", "Sofia", "Dmitri",
    "Kwame", "Svetlana", "Tariq", "Mei", "Abdul", "Leila", "Sven", "Yusuf",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
    "Okafor", "Patel", "Singh", "Zhang", "Tanaka", "Al-Farsi", "Petrov", "Johansson",
    "Muller", "Fischer", "Schneider", "O'Brien", "Murphy", "Nakamura", "Kim",
    "Osei", "Volkov", "Ibrahim", "Chen", "Fernandez", "Costa", "Santos",
]


# ---------------------------------------------------------------------------
# 1. Helper functions
# ---------------------------------------------------------------------------

def deterministic_uuid(rng: random.Random, prefix: str, idx: int) -> str:
    """Generate a reproducible UUID-like string from a seed + index."""
    raw = f"{prefix}-{rng.getrandbits(64):016x}-{idx}"
    h = hashlib.sha256(raw.encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def gen_sort_code(rng: random.Random) -> str:
    return f"{rng.randint(10,99):02d}-{rng.randint(10,99):02d}-{rng.randint(10,99):02d}"


def gen_account_number(rng: random.Random) -> str:
    return f"{rng.randint(10000000, 99999999)}"


def pick(rng: random.Random, population: list, weights: list | None = None):
    return rng.choices(population, weights=weights, k=1)[0]


def gen_amount(rng: random.Random, txn_type: str, segment: str) -> float:
    """
    Return a plausible transaction amount based on type and segment.
    Uses log-normal-ish distributions so most values are small.
    """
    if txn_type == "salary":
        if segment == "sme":
            base = rng.gauss(5500, 2500)
        else:
            base = rng.gauss(2800, 1200)
        return round(max(800, base), 2)

    if txn_type == "card_purchase":
        # Mostly small retail
        base = math.exp(rng.gauss(2.8, 1.1))  # median ~16
        return round(max(0.50, min(base, 9999)), 2)

    if txn_type == "cash_withdrawal":
        # ATM-style: multiples of 10/20
        choices = [10, 20, 30, 40, 50, 60, 80, 100, 150, 200, 250, 300, 500]
        return float(pick(rng, choices, [5, 15, 8, 5, 20, 5, 8, 18, 5, 8, 3, 2, 1]))

    if txn_type == "cash_deposit":
        base = math.exp(rng.gauss(5.5, 1.5))
        return round(max(10, min(base, 50000)), 2)

    if txn_type == "bill_payment":
        base = math.exp(rng.gauss(4.5, 1.0))  # median ~90
        return round(max(5, min(base, 15000)), 2)

    if txn_type == "bank_transfer":
        if segment == "sme":
            base = math.exp(rng.gauss(7.0, 2.0))
        else:
            base = math.exp(rng.gauss(5.0, 1.8))
        return round(max(1, min(base, 500000)), 2)

    if txn_type == "p2p_transfer":
        base = math.exp(rng.gauss(3.5, 1.2))  # median ~33
        return round(max(1, min(base, 10000)), 2)

    if txn_type == "merchant_payout":
        base = math.exp(rng.gauss(7.5, 1.5))
        return round(max(50, min(base, 250000)), 2)

    return round(max(1, math.exp(rng.gauss(4, 1.5))), 2)


def weighted_timestamp(rng: random.Random, start: datetime, end: datetime) -> datetime:
    """
    Generate a timestamp with realistic diurnal and weekly patterns.
    Fewer transactions at night and on weekends.
    """
    total_seconds = int((end - start).total_seconds())
    while True:
        offset = rng.randint(0, total_seconds)
        ts = start + timedelta(seconds=offset)
        hour = ts.hour
        weekday = ts.weekday()  # 0=Mon … 6=Sun

        # Diurnal weight (peak 10-14, low 0-6)
        if 0 <= hour < 6:
            hour_w = 0.05
        elif 6 <= hour < 9:
            hour_w = 0.40
        elif 9 <= hour < 12:
            hour_w = 0.90
        elif 12 <= hour < 14:
            hour_w = 1.00
        elif 14 <= hour < 18:
            hour_w = 0.80
        elif 18 <= hour < 21:
            hour_w = 0.55
        else:
            hour_w = 0.15

        # Weekend discount
        if weekday >= 5:
            day_w = 0.45
        elif weekday == 4:  # Friday
            day_w = 0.90
        else:
            day_w = 1.0

        if rng.random() < hour_w * day_w:
            return ts


def gen_ip_address(rng: random.Random) -> str:
    """Generate a plausible non-reserved IPv4 address."""
    while True:
        a = rng.randint(1, 223)
        if a in (10, 127):
            continue
        b = rng.randint(0, 255)
        if a == 172 and 16 <= b <= 31:
            continue
        if a == 192 and b == 168:
            continue
        c = rng.randint(0, 255)
        d = rng.randint(1, 254)
        return f"{a}.{b}.{c}.{d}"


# ---------------------------------------------------------------------------
# 2. Account and counterparty universe generation
# ---------------------------------------------------------------------------

def build_account_universe(rng: random.Random, n_accounts: int) -> list[dict]:
    """Create the set of accounts with stable attributes."""
    accounts = []
    for i in range(n_accounts):
        segment = pick(rng, CUSTOMER_SEGMENTS, SEGMENT_WEIGHTS)
        risk = pick(rng, RISK_BANDS, RISK_BAND_WEIGHTS)
        currency = pick(rng, CURRENCIES, CURRENCY_WEIGHTS)
        # Account open date: 0–10 years before start
        days_before = rng.randint(30, 3650)
        open_date = (START_DATE - timedelta(days=days_before)).strftime("%Y-%m-%d")
        # Some newer accounts (< 90 days)
        if rng.random() < 0.06:
            days_before = rng.randint(1, 89)
            open_date = (START_DATE + timedelta(days=rng.randint(0, 30)) - timedelta(days=days_before)).strftime("%Y-%m-%d")

        home_country = DOMESTIC_COUNTRY_WEIGHTS.get(currency, ("GB", 0.5))[0]
        if rng.random() < 0.15:
            home_country = pick(rng, COUNTRIES)

        first = pick(rng, FIRST_NAMES)
        last = pick(rng, LAST_NAMES)

        accounts.append({
            "account_id": f"ACC{100000 + i}",
            "customer_name": f"{first} {last}",
            "segment": segment,
            "risk_band": risk,
            "home_currency": currency,
            "home_country": home_country,
            "account_open_date": open_date,
            "sort_code": gen_sort_code(rng),
            # How many txns this account generates (power-law-ish)
            "_activity_weight": max(0.05, rng.paretovariate(1.2) - 1),
            "_salary_payer": pick(rng, SALARY_PAYERS) if segment == "retail" else None,
        })
    return accounts


def build_counterparty_pool(rng: random.Random, accounts: list[dict], n: int = 3000) -> list[str]:
    """External individual counterparty IDs (not in main account set)."""
    pool = []
    for i in range(n):
        pool.append(f"EXT{900000 + i}")
    return pool


# ---------------------------------------------------------------------------
# 3. Transaction generation
# ---------------------------------------------------------------------------

COLUMNS = [
    "transaction_id",
    "timestamp",
    "account_id",
    "customer_name",
    "customer_segment",
    "risk_band",
    "account_open_date",
    "transaction_type",
    "channel",
    "amount",
    "currency",
    "direction",
    "counterparty_id",
    "counterparty_type",
    "counterparty_name",
    "merchant_name",
    "merchant_mcc",
    "merchant_country",
    "origin_country",
    "destination_country",
    "ip_country",
    "ip_address",
    "description",
    "reference",
    "fee_amount",
    "balance_after",
]


def generate_transactions(
    rng: random.Random,
    accounts: list[dict],
    counterparty_pool: list[str],
    n_rows: int,
) -> list[dict]:

    # Pre-compute activity weights for sampling
    act_weights = [a["_activity_weight"] for a in accounts]
    total_w = sum(act_weights)
    act_probs = [w / total_w for w in act_weights]

    # Running balances (fictional)
    balances: dict[str, float] = {}
    for acc in accounts:
        balances[acc["account_id"]] = round(rng.uniform(50, 25000), 2)

    rows: list[dict] = []

    for i in range(n_rows):
        # Pick account (weighted by activity)
        acc = rng.choices(accounts, weights=act_probs, k=1)[0]
        aid = acc["account_id"]

        txn_type = pick(rng, TRANSACTION_TYPES, TXN_TYPE_WEIGHTS)
        channel = pick(rng, CHANNEL_BY_TXN[txn_type])
        cpty_type = pick(rng, CPTY_BY_TXN[txn_type])
        currency = acc["home_currency"]
        ts = weighted_timestamp(rng, START_DATE, END_DATE)
        amount = gen_amount(rng, txn_type, acc["segment"])

        # Direction
        if txn_type in ("salary", "cash_deposit", "merchant_payout"):
            direction = "credit"
        elif txn_type in ("card_purchase", "cash_withdrawal", "bill_payment"):
            direction = "debit"
        elif txn_type in ("bank_transfer", "p2p_transfer"):
            direction = pick(rng, ["debit", "credit"], [0.65, 0.35])
        else:
            direction = "debit"

        # Cross-currency occasionally
        if rng.random() < 0.04 and txn_type in ("bank_transfer", "p2p_transfer", "card_purchase"):
            currency = pick(rng, [c for c in CURRENCIES if c != acc["home_currency"]] or CURRENCIES)

        # Countries
        origin_country = acc["home_country"]
        dest_country = acc["home_country"]
        if txn_type in ("bank_transfer", "p2p_transfer"):
            if rng.random() < 0.12:
                dest_country = pick(rng, COUNTRIES)
        if txn_type == "card_purchase" and rng.random() < 0.08:
            dest_country = pick(rng, COUNTRIES)

        ip_country = origin_country
        if channel in ("mobile_app", "web"):
            if rng.random() < 0.03:
                ip_country = pick(rng, COUNTRIES)

        ip_addr = gen_ip_address(rng) if channel in ("mobile_app", "web", "api") else ""

        # Counterparty
        cpty_id = ""
        cpty_name = ""
        if cpty_type == "individual":
            cpty_id = pick(rng, counterparty_pool)
            cpty_name = f"{pick(rng, FIRST_NAMES)} {pick(rng, LAST_NAMES)}"
        elif cpty_type == "internal_account":
            cpty_id = aid  # same bank
            cpty_name = "INTERNAL"
        elif cpty_type == "payroll_provider":
            cpty_name = acc["_salary_payer"] or pick(rng, SALARY_PAYERS)
            cpty_id = f"PAY{abs(hash(cpty_name)) % 100000:05d}"
        elif cpty_type == "exchange":
            exch_names = ["WISE LTD", "REVOLUT", "CURRENCYFAIR", "OFX", "WORLDREMIT", "XE.COM"]
            cpty_name = pick(rng, exch_names)
            cpty_id = f"EXC{abs(hash(cpty_name)) % 10000:04d}"
        elif cpty_type == "merchant":
            cpty_name = ""  # filled in merchant section
            cpty_id = ""

        # Merchant fields
        merchant_name = ""
        merchant_mcc = ""
        merchant_country = ""

        if txn_type == "card_purchase":
            cat = pick(rng, list(MCC_MAP.keys()),
                       [15, 10, 8, 6, 4, 12, 5, 12, 3, 10])
            mcc, names = MCC_MAP[cat]
            merchant_name = pick(rng, names)
            merchant_mcc = mcc
            merchant_country = dest_country
            cpty_name = merchant_name
            cpty_id = f"MER{abs(hash(merchant_name)) % 100000:05d}"
        elif txn_type == "bill_payment":
            payee = pick(rng, BILL_PAYEES)
            merchant_name = payee
            merchant_mcc = "4900" if "ENERGY" in payee or "GAS" in payee or "WATER" in payee else "9399"
            merchant_country = origin_country
            cpty_name = payee
            cpty_id = f"BIL{abs(hash(payee)) % 100000:05d}"
        elif txn_type == "merchant_payout":
            mn = f"SHOP-{rng.randint(1000,9999)}"
            merchant_name = mn
            merchant_mcc = "5999"
            merchant_country = origin_country
            cpty_name = mn
            cpty_id = f"MER{abs(hash(mn)) % 100000:05d}"

        # Description / narrative
        desc = _build_description(rng, txn_type, merchant_name, cpty_name, direction, amount, currency)

        # Reference
        ref = f"{rng.randint(100000000, 999999999)}"

        # Occasional fee
        fee = 0.0
        if txn_type in ("bank_transfer", "cash_withdrawal") and rng.random() < 0.08:
            fee = round(pick(rng, [0.50, 0.99, 1.50, 2.50, 3.00, 5.00, 10.00, 15.00, 25.00],
                                  [10, 8, 12, 15, 10, 8, 4, 2, 1]), 2)
        if dest_country != origin_country and txn_type == "bank_transfer" and rng.random() < 0.35:
            fee = round(rng.uniform(2.50, 30.00), 2)

        # Balance
        if direction == "debit":
            balances[aid] = round(balances.get(aid, 1000) - amount - fee, 2)
        else:
            balances[aid] = round(balances.get(aid, 1000) + amount, 2)

        # Prevent deeply negative (simulate overdraft limit)
        if balances[aid] < -2500:
            balances[aid] = round(rng.uniform(-2000, 500), 2)

        txn_id = deterministic_uuid(rng, "TXN", i)

        rows.append({
            "transaction_id":   txn_id,
            "timestamp":        ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "account_id":       aid,
            "customer_name":    acc["customer_name"],
            "customer_segment": acc["segment"],
            "risk_band":        acc["risk_band"],
            "account_open_date": acc["account_open_date"],
            "transaction_type": txn_type,
            "channel":          channel,
            "amount":           amount,
            "currency":         currency,
            "direction":        direction,
            "counterparty_id":  cpty_id,
            "counterparty_type": cpty_type,
            "counterparty_name": cpty_name,
            "merchant_name":    merchant_name,
            "merchant_mcc":     merchant_mcc,
            "merchant_country": merchant_country,
            "origin_country":   origin_country,
            "destination_country": dest_country,
            "ip_country":       ip_country,
            "ip_address":       ip_addr,
            "description":      desc,
            "reference":        ref,
            "fee_amount":       fee if fee > 0 else "",
            "balance_after":    balances[aid],
        })

    # Sort by timestamp
    rows.sort(key=lambda r: r["timestamp"])
    return rows


def _build_description(rng, txn_type, merchant_name, cpty_name, direction, amount, currency):
    """Build a bank-statement-style narrative."""
    if txn_type == "card_purchase":
        store_num = rng.randint(100, 9999)
        return f"{merchant_name} {store_num}"

    if txn_type == "salary":
        return f"SALARY {cpty_name}"

    if txn_type == "bill_payment":
        return f"DD {merchant_name}" if rng.random() < 0.6 else f"SO {merchant_name}"

    if txn_type == "cash_withdrawal":
        return f"ATM WITHDRAWAL" if rng.random() < 0.7 else f"CASH WDL BRANCH"

    if txn_type == "cash_deposit":
        return f"CASH DEPOSIT" if rng.random() < 0.6 else f"BRANCH DEPOSIT"

    if txn_type == "bank_transfer":
        if direction == "debit":
            return f"TFR TO {cpty_name}" if cpty_name else f"BANK TRANSFER OUT"
        else:
            return f"TFR FROM {cpty_name}" if cpty_name else f"BANK TRANSFER IN"

    if txn_type == "p2p_transfer":
        if direction == "debit":
            return f"P2P TO {cpty_name}"
        else:
            return f"P2P FROM {cpty_name}"

    if txn_type == "merchant_payout":
        return f"MERCHANT SETTLEMENT {merchant_name}"

    return f"TRANSACTION {txn_type.upper()}"


# ---------------------------------------------------------------------------
# 4. Inject naturally "unusual" patterns (no labels)
# ---------------------------------------------------------------------------

def inject_organic_anomalies(rng: random.Random, rows: list[dict], accounts: list[dict],
                             counterparty_pool: list[str]) -> list[dict]:
    """
    Overlay a small number of naturally unusual-but-plausible behaviours
    onto the already-generated dataset.  These are NOT labelled.
    """
    extra: list[dict] = []

    # --- Pattern A: a few accounts with burst transfer activity ---
    burst_accounts = rng.sample(accounts, k=min(30, len(accounts)))
    for acc in burst_accounts:
        burst_day = START_DATE + timedelta(days=rng.randint(5, 85))
        n_burst = rng.randint(5, 18)
        for j in range(n_burst):
            ts = burst_day + timedelta(minutes=rng.randint(0, 120))
            amt = round(rng.uniform(200, 4999), 2)  # just under 5k
            cpty = pick(rng, counterparty_pool)
            txn_id = deterministic_uuid(rng, "BURST", len(rows) + len(extra))
            extra.append({
                "transaction_id":   txn_id,
                "timestamp":        ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "account_id":       acc["account_id"],
                "customer_name":    acc["customer_name"],
                "customer_segment": acc["segment"],
                "risk_band":        acc["risk_band"],
                "account_open_date": acc["account_open_date"],
                "transaction_type": "bank_transfer",
                "channel":          pick(rng, ["mobile_app", "web"]),
                "amount":           amt,
                "currency":         acc["home_currency"],
                "direction":        "debit",
                "counterparty_id":  cpty,
                "counterparty_type": "individual",
                "counterparty_name": f"{pick(rng, FIRST_NAMES)} {pick(rng, LAST_NAMES)}",
                "merchant_name":    "",
                "merchant_mcc":     "",
                "merchant_country": "",
                "origin_country":   acc["home_country"],
                "destination_country": pick(rng, COUNTRIES),
                "ip_country":       acc["home_country"],
                "ip_address":       gen_ip_address(rng),
                "description":      f"TFR TO {pick(rng, FIRST_NAMES)} {pick(rng, LAST_NAMES)}",
                "reference":        f"{rng.randint(100000000,999999999)}",
                "fee_amount":       "",
                "balance_after":    round(rng.uniform(-500, 5000), 2),
            })

    # --- Pattern B: round-amount cash deposits ---
    round_accounts = rng.sample(accounts, k=min(20, len(accounts)))
    for acc in round_accounts:
        for _ in range(rng.randint(3, 8)):
            ts = weighted_timestamp(rng, START_DATE, END_DATE)
            amt = float(pick(rng, [1000, 2000, 3000, 5000, 7500, 9900]))
            txn_id = deterministic_uuid(rng, "CASHD", len(rows) + len(extra))
            extra.append({
                "transaction_id":   txn_id,
                "timestamp":        ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "account_id":       acc["account_id"],
                "customer_name":    acc["customer_name"],
                "customer_segment": acc["segment"],
                "risk_band":        acc["risk_band"],
                "account_open_date": acc["account_open_date"],
                "transaction_type": "cash_deposit",
                "channel":          pick(rng, ["atm", "branch"]),
                "amount":           amt,
                "currency":         acc["home_currency"],
                "direction":        "credit",
                "counterparty_id":  acc["account_id"],
                "counterparty_type": "internal_account",
                "counterparty_name": "INTERNAL",
                "merchant_name":    "",
                "merchant_mcc":     "",
                "merchant_country": "",
                "origin_country":   acc["home_country"],
                "destination_country": acc["home_country"],
                "ip_country":       acc["home_country"],
                "ip_address":       "",
                "description":      "CASH DEPOSIT",
                "reference":        f"{rng.randint(100000000,999999999)}",
                "fee_amount":       "",
                "balance_after":    round(rng.uniform(2000, 30000), 2),
            })

    # --- Pattern C: geo-inconsistent card usage ---
    travel_accounts = rng.sample(accounts, k=min(15, len(accounts)))
    for acc in travel_accounts:
        foreign = pick(rng, [c for c in COUNTRIES if c != acc["home_country"]])
        base_day = START_DATE + timedelta(days=rng.randint(10, 80))
        for _ in range(rng.randint(4, 12)):
            ts = base_day + timedelta(hours=rng.randint(0, 72))
            cat = pick(rng, list(MCC_MAP.keys()))
            mcc, names = MCC_MAP[cat]
            mname = pick(rng, names)
            amt = round(math.exp(rng.gauss(3.0, 1.0)), 2)
            txn_id = deterministic_uuid(rng, "GEOC", len(rows) + len(extra))
            extra.append({
                "transaction_id":   txn_id,
                "timestamp":        ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "account_id":       acc["account_id"],
                "customer_name":    acc["customer_name"],
                "customer_segment": acc["segment"],
                "risk_band":        acc["risk_band"],
                "account_open_date": acc["account_open_date"],
                "transaction_type": "card_purchase",
                "channel":          "card_pos",
                "amount":           amt,
                "currency":         pick(rng, CURRENCIES),
                "direction":        "debit",
                "counterparty_id":  f"MER{abs(hash(mname)) % 100000:05d}",
                "counterparty_type": "merchant",
                "counterparty_name": mname,
                "merchant_name":    mname,
                "merchant_mcc":     mcc,
                "merchant_country": foreign,
                "origin_country":   foreign,
                "destination_country": foreign,
                "ip_country":       foreign if rng.random() < 0.5 else acc["home_country"],
                "ip_address":       "",
                "description":      f"{mname} {rng.randint(100,9999)}",
                "reference":        f"{rng.randint(100000000,999999999)}",
                "fee_amount":       "",
                "balance_after":    round(rng.uniform(200, 8000), 2),
            })

    return extra


# ---------------------------------------------------------------------------
# 5. Validation / summary
# ---------------------------------------------------------------------------

def validate_and_report(rows: list[dict]):
    print("\n" + "=" * 70)
    print("VALIDATION REPORT")
    print("=" * 70)

    n = len(rows)
    print(f"Total rows              : {n:,}")
    accts = set(r["account_id"] for r in rows)
    print(f"Unique accounts         : {len(accts):,}")

    timestamps = [r["timestamp"] for r in rows]
    print(f"Date range              : {min(timestamps)} → {max(timestamps)}")

    # Null / empty rates
    print("\nNull / empty rates per column:")
    for col in COLUMNS:
        empty = sum(1 for r in rows if r.get(col, "") in ("", None))
        pct = empty / n * 100
        if pct > 0:
            print(f"  {col:30s} {pct:6.2f}%  ({empty:,} rows)")

    # Duplicate transaction_id
    tid_counts = Counter(r["transaction_id"] for r in rows)
    dups = sum(1 for c in tid_counts.values() if c > 1)
    print(f"\nDuplicate transaction_ids: {dups}")

    # Top 10 transaction types
    tt = Counter(r["transaction_type"] for r in rows)
    print("\nTop transaction types:")
    for t, c in tt.most_common(10):
        print(f"  {t:25s} {c:>7,}  ({c/n*100:5.1f}%)")

    # Top channels
    ch = Counter(r["channel"] for r in rows)
    print("\nTop channels:")
    for t, c in ch.most_common(10):
        print(f"  {t:25s} {c:>7,}  ({c/n*100:5.1f}%)")

    # Currency split
    cu = Counter(r["currency"] for r in rows)
    print("\nCurrency split:")
    for t, c in cu.most_common():
        print(f"  {t:25s} {c:>7,}  ({c/n*100:5.1f}%)")

    # Direction split
    di = Counter(r["direction"] for r in rows)
    print("\nDirection split:")
    for t, c in di.most_common():
        print(f"  {t:25s} {c:>7,}  ({c/n*100:5.1f}%)")

    print("=" * 70 + "\n")


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Synthetic AML transaction generator")
    parser.add_argument("--rows", type=int, default=NUM_ROWS, help="Number of base rows")
    parser.add_argument("--seed", type=int, default=SEED, help="Random seed")
    parser.add_argument("--out", type=str, default="transactions.csv", help="Output CSV path")
    args = parser.parse_args()

    rng = random.Random(args.seed)

    print(f"[1/5] Building account universe (seed={args.seed}) …")
    n_accounts = rng.randint(NUM_ACCOUNTS_MIN, NUM_ACCOUNTS_MAX)
    accounts = build_account_universe(rng, n_accounts)
    print(f"       Created {len(accounts):,} accounts")

    print(f"[2/5] Building counterparty pool …")
    cpty_pool = build_counterparty_pool(rng, accounts, n=3000)

    print(f"[3/5] Generating {args.rows:,} base transactions …")
    rows = generate_transactions(rng, accounts, cpty_pool, args.rows)

    print(f"[4/5] Injecting organic anomaly patterns …")
    extra = inject_organic_anomalies(rng, rows, accounts, cpty_pool)
    rows.extend(extra)
    rows.sort(key=lambda r: r["timestamp"])
    print(f"       Added {len(extra):,} overlay rows → {len(rows):,} total")

    print(f"[5/5] Writing {args.out} …")
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    fsize = os.path.getsize(args.out)
    print(f"       Done. File size: {fsize / 1024 / 1024:.1f} MB")

    validate_and_report(rows)


if __name__ == "__main__":
    main()
