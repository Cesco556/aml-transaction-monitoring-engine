"""Tests for external_id canonicalization and idempotent ingest."""

from datetime import UTC, datetime

from aml_monitoring.ingest._idempotency import compute_external_id


def _ts(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def test_external_id_same_for_canonical_equivalents() -> None:
    """Different whitespace/casing yields same external_id."""
    base = (
        1,
        _ts("2025-01-01T10:00:00Z"),
        1000.0,
        "usd",
        "  Acme Corp  ",
        "OUT",
    )
    variants = [
        (1, _ts("2025-01-01T10:00:00Z"), 1000.0, "USD", "acme corp", "out"),
        (1, _ts("2025-01-01T10:00:00+00:00"), 1000.00, "usd", "Acme Corp", "Out"),
        (1, _ts("2025-01-01T10:00:00Z"), 1000, "  usd  ", "  ACME CORP  ", "  out  "),
    ]
    ids = [compute_external_id(*v) for v in variants]
    assert len(set(ids)) == 1
    assert ids[0] == compute_external_id(*base)


def test_external_id_amount_two_decimal_places() -> None:
    """Amount normalized to 2dp: 1000.1 and 1000.10 same; 1000.12 different from 1000.1."""
    base = (1, _ts("2025-01-01T12:00:00Z"), 1000.1, "USD", "x", "out")
    same = (1, _ts("2025-01-01T12:00:00Z"), 1000.10, "USD", "x", "out")
    diff = (1, _ts("2025-01-01T12:00:00Z"), 1000.12, "USD", "x", "out")
    assert compute_external_id(*base) == compute_external_id(*same)
    assert compute_external_id(*base) != compute_external_id(*diff)


def test_external_id_currency_upper() -> None:
    """Currency normalized to upper: usd, USD, Usd same."""
    base = (1, _ts("2025-01-01T12:00:00Z"), 100.0, "USD", "", "")
    assert compute_external_id(
        1, _ts("2025-01-01T12:00:00Z"), 100.0, "usd", "", ""
    ) == compute_external_id(*base)
    assert compute_external_id(
        1, _ts("2025-01-01T12:00:00Z"), 100.0, "  eur  ", "", ""
    ) == compute_external_id(1, _ts("2025-01-01T12:00:00Z"), 100.0, "EUR", "", "")


def test_external_id_counterparty_direction_lower_strip() -> None:
    """Counterparty and direction lower+strip: IN/out and in/OUT same."""
    a = compute_external_id(1, _ts("2025-01-01T12:00:00Z"), 50.0, "USD", "  Payee  ", "  IN  ")
    b = compute_external_id(1, _ts("2025-01-01T12:00:00Z"), 50.0, "USD", "payee", "in")
    assert a == b


def test_external_id_ts_utc_canonical() -> None:
    """Naive and UTC-aware same instant yield same id."""
    naive = datetime(2025, 1, 1, 10, 0, 0)
    utc = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
    id_naive = compute_external_id(1, naive, 100.0, "USD", "", "")
    id_utc = compute_external_id(1, utc, 100.0, "USD", "", "")
    assert id_naive == id_utc


def test_external_id_different_inputs_different_id() -> None:
    """Any field change changes external_id."""
    base = (1, _ts("2025-01-01T10:00:00Z"), 1000.0, "USD", "acme", "out")
    base_id = compute_external_id(*base)
    assert compute_external_id(2, base[1], base[2], base[3], base[4], base[5]) != base_id
    assert (
        compute_external_id(1, _ts("2025-01-01T10:00:01Z"), base[2], base[3], base[4], base[5])
        != base_id
    )
    assert compute_external_id(1, base[1], 1000.01, base[3], base[4], base[5]) != base_id
    assert compute_external_id(1, base[1], base[2], "EUR", base[4], base[5]) != base_id
    assert compute_external_id(1, base[1], base[2], base[3], "other", base[5]) != base_id
    assert compute_external_id(1, base[1], base[2], base[3], base[4], "in") != base_id
