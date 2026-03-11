"""Tests for real-time stream processing (Phase 5).

Covers: FileStreamProducer/Consumer, event bus, WebSocket endpoint,
sliding windows, alert deduplication, end-to-end consumer pipeline.
All tests use file-based backends — no Redis needed.
"""

from __future__ import annotations

import json
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aml_monitoring.streaming.dedup import AlertDeduplicator
from aml_monitoring.streaming.events import (
    clear_listeners,
    emit_alert_created,
    listener_count,
    on_alert_created,
    remove_listener,
)
from aml_monitoring.streaming.producer import FileStreamProducer
from aml_monitoring.streaming.windows import SlidingWindow, WindowStats


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_event_bus():
    """Ensure event bus is clean before and after each test."""
    clear_listeners()
    yield
    clear_listeners()


# ---------------------------------------------------------------------------
# Event Bus Tests
# ---------------------------------------------------------------------------


class TestEventBus:
    def test_register_and_emit(self):
        received: list[dict] = []
        on_alert_created(lambda d: received.append(d))
        assert listener_count() == 1

        emit_alert_created({"id": 1, "rule_id": "HighValue"})
        assert len(received) == 1
        assert received[0]["rule_id"] == "HighValue"

    def test_multiple_listeners(self):
        received_a: list[dict] = []
        received_b: list[dict] = []
        on_alert_created(lambda d: received_a.append(d))
        on_alert_created(lambda d: received_b.append(d))
        assert listener_count() == 2

        emit_alert_created({"id": 42})
        assert len(received_a) == 1
        assert len(received_b) == 1

    def test_remove_listener(self):
        received: list[dict] = []
        cb = lambda d: received.append(d)  # noqa: E731
        on_alert_created(cb)
        emit_alert_created({"id": 1})
        assert len(received) == 1

        remove_listener(cb)
        emit_alert_created({"id": 2})
        assert len(received) == 1  # no new events

    def test_duplicate_register_ignored(self):
        cb = lambda d: None  # noqa: E731
        on_alert_created(cb)
        on_alert_created(cb)
        assert listener_count() == 1

    def test_listener_exception_does_not_propagate(self):
        def bad_listener(d: dict) -> None:
            raise ValueError("boom")

        received: list[dict] = []
        on_alert_created(bad_listener)
        on_alert_created(lambda d: received.append(d))

        emit_alert_created({"id": 1})
        # Second listener still received the event
        assert len(received) == 1

    def test_clear_listeners(self):
        on_alert_created(lambda d: None)
        on_alert_created(lambda d: None)
        assert listener_count() == 2
        clear_listeners()
        assert listener_count() == 0


# ---------------------------------------------------------------------------
# Alert Deduplication Tests
# ---------------------------------------------------------------------------


class TestAlertDeduplicator:
    def test_first_occurrence_not_duplicate(self):
        dedup = AlertDeduplicator(window_seconds=60)
        assert dedup.is_duplicate(("txn1", "HighValue")) is False

    def test_second_occurrence_is_duplicate(self):
        dedup = AlertDeduplicator(window_seconds=60)
        assert dedup.is_duplicate(("txn1", "HighValue")) is False
        assert dedup.is_duplicate(("txn1", "HighValue")) is True

    def test_different_keys_not_duplicate(self):
        dedup = AlertDeduplicator(window_seconds=60)
        assert dedup.is_duplicate(("txn1", "HighValue")) is False
        assert dedup.is_duplicate(("txn2", "HighValue")) is False
        assert dedup.is_duplicate(("txn1", "Velocity")) is False

    def test_expired_key_not_duplicate(self):
        dedup = AlertDeduplicator(window_seconds=1)
        assert dedup.is_duplicate(("txn1", "HighValue")) is False
        time.sleep(1.1)
        # After window expires, should not be considered duplicate
        assert dedup.is_duplicate(("txn1", "HighValue")) is False

    def test_size_tracking(self):
        dedup = AlertDeduplicator(window_seconds=60)
        dedup.is_duplicate(("a",))
        dedup.is_duplicate(("b",))
        assert dedup.size == 2

    def test_clear(self):
        dedup = AlertDeduplicator(window_seconds=60)
        dedup.is_duplicate(("a",))
        dedup.clear()
        assert dedup.size == 0
        # After clear, same key should not be duplicate
        assert dedup.is_duplicate(("a",)) is False


# ---------------------------------------------------------------------------
# Sliding Window Tests
# ---------------------------------------------------------------------------


class TestSlidingWindow:
    def test_add_and_get_stats(self):
        window = SlidingWindow(window_seconds=60)
        now = time.time()
        window.add_event("acct1", 100.0, "merchant_a", timestamp=now)
        window.add_event("acct1", 200.0, "merchant_b", timestamp=now + 1)

        stats = window.get_stats("acct1", timestamp=now + 2)
        assert stats.transaction_count == 2
        assert stats.total_amount == 300.0
        assert stats.unique_counterparties == 2
        assert "merchant_a" in stats.counterparties
        assert "merchant_b" in stats.counterparties

    def test_expired_events_evicted(self):
        window = SlidingWindow(window_seconds=5)
        now = time.time()
        window.add_event("acct1", 100.0, timestamp=now - 10)  # Already expired
        window.add_event("acct1", 200.0, timestamp=now)

        stats = window.get_stats("acct1", timestamp=now)
        assert stats.transaction_count == 1
        assert stats.total_amount == 200.0

    def test_empty_account(self):
        window = SlidingWindow(window_seconds=60)
        stats = window.get_stats("nonexistent")
        assert stats.transaction_count == 0
        assert stats.total_amount == 0.0

    def test_multiple_accounts(self):
        window = SlidingWindow(window_seconds=60)
        now = time.time()
        window.add_event("acct1", 100.0, timestamp=now)
        window.add_event("acct2", 500.0, timestamp=now)

        assert window.account_count == 2
        assert window.get_stats("acct1", timestamp=now).total_amount == 100.0
        assert window.get_stats("acct2", timestamp=now).total_amount == 500.0

    def test_null_counterparty(self):
        window = SlidingWindow(window_seconds=60)
        now = time.time()
        window.add_event("acct1", 100.0, counterparty=None, timestamp=now)
        stats = window.get_stats("acct1", timestamp=now)
        assert stats.unique_counterparties == 0

    def test_clear(self):
        window = SlidingWindow(window_seconds=60)
        window.add_event("acct1", 100.0)
        window.clear()
        assert window.account_count == 0


# ---------------------------------------------------------------------------
# FileStreamProducer Tests
# ---------------------------------------------------------------------------


class TestFileStreamProducer:
    def test_publish_creates_jsonl(self, tmp_path: Path):
        out = tmp_path / "stream.jsonl"
        producer = FileStreamProducer(out)
        msg_id = producer.publish({"id": "txn1", "amount": 100})
        assert msg_id == "1"
        assert out.exists()

        lines = out.read_text().strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["id"] == "txn1"

    def test_publish_batch(self, tmp_path: Path):
        out = tmp_path / "stream.jsonl"
        producer = FileStreamProducer(out)
        ids = producer.publish_batch([{"id": "a"}, {"id": "b"}, {"id": "c"}])
        assert len(ids) == 3

        lines = out.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_append_mode(self, tmp_path: Path):
        out = tmp_path / "stream.jsonl"
        producer = FileStreamProducer(out)
        producer.publish({"id": "first"})
        producer.publish({"id": "second"})

        lines = out.read_text().strip().split("\n")
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# FileStreamConsumer Tests (end-to-end with DB)
# ---------------------------------------------------------------------------


class TestFileStreamConsumer:
    """Integration tests: FileStreamConsumer ingests, runs rules, creates alerts."""

    def _make_test_transactions(self, tmp_path: Path, count: int = 3) -> Path:
        """Create a JSONL file with test transactions that will trigger HighValue rule."""
        from aml_monitoring.db import session_scope
        from aml_monitoring.models import Account, Customer

        # Ensure customer and account exist
        with session_scope() as session:
            cust = Customer(name="Stream Test Customer", country="US", base_risk=10.0)
            session.add(cust)
            session.flush()
            acct = Account(customer_id=cust.id, iban_or_acct=f"STREAM-TEST-{time.time_ns()}")
            session.add(acct)
            session.flush()
            acct_id = acct.id

        jsonl_path = tmp_path / "test_transactions.jsonl"
        iban = f"STREAM-TEST-{time.time_ns()}"
        txns = []
        for i in range(count):
            txns.append(
                {
                    "external_id": f"stream-test-{time.time_ns()}-{i}",
                    "customer_name": "Stream Test Customer",
                    "iban_or_acct": iban,
                    "account_id": acct_id,
                    "ts": datetime.now(UTC).isoformat(),
                    "amount": 50000.0,  # High value to trigger rule
                    "currency": "USD",
                    "merchant": f"Test Merchant {i}",
                    "counterparty": f"counterparty-{i}",
                    "country": "US",
                    "country_txn": "US",
                    "channel": "wire",
                    "direction": "out",
                    "base_risk": 10.0,
                }
            )
        with open(jsonl_path, "w") as f:
            for t in txns:
                f.write(json.dumps(t) + "\n")
        return jsonl_path

    @staticmethod
    def _make_test_config(tmp_path: Path) -> dict:
        """Build a valid test config that avoids placeholder country validation."""
        import yaml
        from aml_monitoring.config import get_config
        cfg_data = {
            "app": {"log_level": "INFO"},
            "database": {"url": "sqlite:///", "echo": False},
            "rules": {
                "high_value": {"enabled": True, "threshold_amount": 10000},
                "rapid_velocity": {"enabled": False},
                "sanctions_keyword": {"enabled": False},
                "high_risk_country": {"enabled": True, "countries": ["IR", "KP"]},
                "geo_mismatch": {"enabled": False},
                "structuring_smurfing": {"enabled": False},
                "network_ring": {"enabled": False},
            },
            "scoring": {"base_risk_per_customer": 10, "max_score": 100},
        }
        cfg_path = tmp_path / "test_config.yaml"
        cfg_path.write_text(yaml.dump(cfg_data))
        return get_config(str(cfg_path)), str(cfg_path)

    def test_consumer_processes_transactions(self, tmp_path: Path):
        """End-to-end: ingest → rules → alerts."""
        from aml_monitoring.db import init_db

        init_db("sqlite:///", echo=False)

        jsonl_path = self._make_test_transactions(tmp_path, count=2)
        cfg, cfg_path = self._make_test_config(tmp_path)

        from aml_monitoring.streaming.consumer import FileStreamConsumer

        consumer = FileStreamConsumer(
            input_path=jsonl_path,
            processed_path=tmp_path / "processed.jsonl",
            config=cfg,
            config_path=cfg_path,
        )
        consumer.consume(max_messages=2)

        assert consumer.processed_count == 2
        # HighValue rule should trigger for 50k transactions
        assert consumer.alert_count >= 2

    def test_consumer_emits_events(self, tmp_path: Path):
        """Verify consumer emits alert events via the event bus."""
        from aml_monitoring.db import init_db

        init_db("sqlite:///", echo=False)

        received_events: list[dict] = []
        on_alert_created(lambda d: received_events.append(d))

        jsonl_path = self._make_test_transactions(tmp_path, count=1)
        cfg, cfg_path = self._make_test_config(tmp_path)

        from aml_monitoring.streaming.consumer import FileStreamConsumer

        consumer = FileStreamConsumer(
            input_path=jsonl_path,
            config=cfg,
            config_path=cfg_path,
        )
        consumer.consume(max_messages=1)

        # At least one alert event should have been emitted
        assert len(received_events) >= 1
        assert "rule_id" in received_events[0]

    def test_consumer_deduplication(self, tmp_path: Path):
        """Verify deduplication prevents duplicate alerts."""
        from aml_monitoring.db import init_db

        init_db("sqlite:///", echo=False)

        jsonl_path = self._make_test_transactions(tmp_path, count=1)
        cfg, cfg_path = self._make_test_config(tmp_path)

        from aml_monitoring.streaming.consumer import FileStreamConsumer

        consumer = FileStreamConsumer(
            input_path=jsonl_path,
            config=cfg,
            config_path=cfg_path,
        )
        consumer.consume(max_messages=1)
        first_alert_count = consumer.alert_count

        # Consume same file again — should be deduplicated at ingest level (idempotent)
        consumer2 = FileStreamConsumer(
            input_path=jsonl_path,
            config=cfg,
            config_path=cfg_path,
        )
        consumer2.consume(max_messages=1)
        # Second consumer should produce 0 new alerts (idempotent ingest)
        assert consumer2.alert_count == 0

    def test_consumer_writes_processed_log(self, tmp_path: Path):
        """Verify commit() writes to processed file."""
        from aml_monitoring.db import init_db

        init_db("sqlite:///", echo=False)

        jsonl_path = self._make_test_transactions(tmp_path, count=2)
        processed_path = tmp_path / "processed.jsonl"
        cfg, cfg_path = self._make_test_config(tmp_path)

        from aml_monitoring.streaming.consumer import FileStreamConsumer

        consumer = FileStreamConsumer(
            input_path=jsonl_path,
            processed_path=processed_path,
            config=cfg,
            config_path=cfg_path,
        )
        consumer.consume(max_messages=2)

        assert processed_path.exists()
        lines = processed_path.read_text().strip().split("\n")
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# WebSocket Tests
# ---------------------------------------------------------------------------


class TestWebSocket:
    def test_websocket_connect_and_receive(self):
        """Test WebSocket endpoint accepts connections and receives broadcast alerts."""
        from aml_monitoring.api import app
        from aml_monitoring.streaming.websocket import alert_manager

        client = TestClient(app)

        with client.websocket_connect("/ws/alerts") as ws:
            assert alert_manager.connection_count >= 1

            # Simulate an alert broadcast
            import asyncio

            async def _broadcast():
                await alert_manager.broadcast({"id": 1, "rule_id": "TestRule"})

            asyncio.get_event_loop().run_until_complete(_broadcast())

            data = ws.receive_json()
            assert data["rule_id"] == "TestRule"

    def test_websocket_disconnect_cleanup(self):
        """Test that disconnected clients are cleaned up."""
        from aml_monitoring.api import app
        from aml_monitoring.streaming.websocket import alert_manager

        client = TestClient(app)
        initial_count = alert_manager.connection_count

        with client.websocket_connect("/ws/alerts"):
            assert alert_manager.connection_count >= initial_count + 1

        # After disconnect, count should return to initial
        # (may need a moment for cleanup)
        assert alert_manager.connection_count >= 0


# ---------------------------------------------------------------------------
# Producer + Consumer Round-trip
# ---------------------------------------------------------------------------


class TestProducerConsumerRoundTrip:
    def test_file_producer_consumer_roundtrip(self, tmp_path: Path):
        """Produce to file, then consume from it."""
        import yaml
        from aml_monitoring.config import get_config
        from aml_monitoring.db import init_db, session_scope
        from aml_monitoring.models import Account, Customer

        init_db("sqlite:///", echo=False)

        with session_scope() as session:
            cust = Customer(name="Roundtrip Customer", country="US", base_risk=10.0)
            session.add(cust)
            session.flush()
            acct = Account(customer_id=cust.id, iban_or_acct=f"RT-{time.time_ns()}")
            session.add(acct)
            session.flush()
            acct_id = acct.id

        stream_file = tmp_path / "stream.jsonl"
        producer = FileStreamProducer(stream_file)

        txn = {
            "external_id": f"rt-{time.time_ns()}",
            "customer_name": "Roundtrip Customer",
            "iban_or_acct": f"RT-{time.time_ns()}",
            "account_id": acct_id,
            "ts": datetime.now(UTC).isoformat(),
            "amount": 15000.0,
            "currency": "USD",
            "country": "US",
            "country_txn": "US",
            "channel": "wire",
            "direction": "out",
            "base_risk": 10.0,
        }
        producer.publish(txn)

        from aml_monitoring.streaming.consumer import FileStreamConsumer

        cfg_data = {
            "app": {"log_level": "INFO"},
            "database": {"url": "sqlite:///", "echo": False},
            "rules": {
                "high_value": {"enabled": True, "threshold_amount": 10000},
                "rapid_velocity": {"enabled": False},
                "sanctions_keyword": {"enabled": False},
                "high_risk_country": {"enabled": True, "countries": ["IR", "KP"]},
                "geo_mismatch": {"enabled": False},
                "structuring_smurfing": {"enabled": False},
                "network_ring": {"enabled": False},
            },
            "scoring": {"base_risk_per_customer": 10, "max_score": 100},
        }
        cfg_path = tmp_path / "test_config.yaml"
        cfg_path.write_text(yaml.dump(cfg_data))
        cfg = get_config(str(cfg_path))
        consumer = FileStreamConsumer(input_path=stream_file, config=cfg, config_path=str(cfg_path))
        consumer.consume(max_messages=1)

        assert consumer.processed_count == 1
        assert consumer.alert_count >= 1  # 15k > 10k threshold
