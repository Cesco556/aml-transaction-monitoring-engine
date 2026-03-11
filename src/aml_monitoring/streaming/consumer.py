"""Stream consumers: read transactions from Redis Streams or JSONL files,
run rules, create alerts — all in one pass."""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from aml_monitoring.streaming.dedup import AlertDeduplicator
from aml_monitoring.streaming.events import emit_alert_created
from aml_monitoring.streaming.windows import SlidingWindow

log = logging.getLogger(__name__)


class StreamConsumer(ABC):
    """Abstract base for stream consumers.

    Subclasses implement ``consume()`` to read messages and ``commit()``
    to acknowledge processed messages. ``process_message()`` is the shared
    pipeline: ingest → rules → alert creation → event emission.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        batch_size: int = 10,
        poll_interval_ms: int = 1000,
        config_path: str | None = None,
    ) -> None:
        self.config = config or {}
        self.config_path = config_path
        self.batch_size = batch_size
        self.poll_interval_ms = poll_interval_ms
        self.processed_count = 0
        self.alert_count = 0

        # Optional components
        dedup_cfg = self.config.get("streaming", {}).get("deduplication", {})
        if dedup_cfg.get("enabled", True):
            window = int(dedup_cfg.get("window_seconds", 3600))
            self.deduplicator: AlertDeduplicator | None = AlertDeduplicator(window_seconds=window)
        else:
            self.deduplicator = None

        self.window = SlidingWindow(window_seconds=900)

    @abstractmethod
    def consume(self, max_messages: int | None = None) -> None:
        """Start consuming messages. If max_messages is set, stop after that many."""
        ...

    @abstractmethod
    def commit(self, message_id: str) -> None:
        """Acknowledge a processed message."""
        ...

    def process_message(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        """Process a single transaction message through the rules engine.

        Returns list of alert dicts created (may be empty).
        """
        from aml_monitoring import ENGINE_VERSION, RULES_VERSION
        from aml_monitoring.config import get_config, get_config_hash
        from aml_monitoring.db import session_scope
        from aml_monitoring.models import Account, Alert, Customer, Transaction
        from aml_monitoring.rules import get_all_rules
        from aml_monitoring.rules.base import RuleContext
        from aml_monitoring.schemas import RuleResult
        from aml_monitoring.scoring import compute_transaction_risk

        from sqlalchemy import select

        config = get_config(self.config_path) if self.config_path else (self.config or {})
        config_hash = get_config_hash(config)
        rules = get_all_rules(config)

        scoring_cfg = config.get("scoring", {})
        base_risk = float(scoring_cfg.get("base_risk_per_customer", 10))
        max_score = float(scoring_cfg.get("max_score", 100))
        thresholds = scoring_cfg.get("thresholds", {})
        low_t = float(thresholds.get("low", 33))
        med_t = float(thresholds.get("medium", 66))

        created_alerts: list[dict[str, Any]] = []

        # Parse transaction fields from raw message
        customer_name = raw.get("customer_name") or "Unknown"
        country = (raw.get("country") or "XXX")[:3]
        iban = (raw.get("iban_or_acct") or "").strip()
        if not iban:
            log.warning("Transaction missing iban_or_acct, skipping")
            self.processed_count += 1
            return created_alerts

        from datetime import datetime, UTC

        ts_raw = raw.get("ts", "")
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            ts = datetime.now(UTC)

        amount = float(raw.get("amount", 0))
        currency = (raw.get("currency") or "USD")[:3]
        merchant = raw.get("merchant") or None
        counterparty = raw.get("counterparty") or None
        country_txn = raw.get("country_txn") or raw.get("country") or None
        channel = raw.get("channel") or None
        direction = raw.get("direction") or None
        raw_base_risk = float(raw.get("base_risk", 10))

        # Direct ingest: create or find customer/account, insert transaction
        with session_scope() as session:
            # Upsert account by iban
            acct = session.execute(
                select(Account).where(Account.iban_or_acct == iban)
            ).scalar_one_or_none()
            if acct:
                cust = session.execute(
                    select(Customer).where(Customer.id == acct.customer_id)
                ).scalar_one_or_none()
            else:
                cust = Customer(name=customer_name, country=country, base_risk=raw_base_risk)
                session.add(cust)
                session.flush()
                acct = Account(customer_id=cust.id, iban_or_acct=iban)
                session.add(acct)
                session.flush()

            # Compute external_id for idempotency
            from aml_monitoring.ingest._idempotency import external_id_for_row

            external_id = external_id_for_row(
                raw.get("external_id"),
                acct.id, ts, amount, currency, counterparty, direction,
            )

            # Check for duplicate
            existing = session.execute(
                select(Transaction.id).where(Transaction.external_id == external_id)
            ).first()
            if existing:
                log.debug("Transaction already ingested (idempotent), skipping rules")
                self.processed_count += 1
                return created_alerts

            txn = Transaction(
                external_id=external_id,
                account_id=acct.id,
                ts=ts,
                amount=amount,
                currency=currency,
                merchant=merchant,
                counterparty=counterparty,
                country=country_txn,
                channel=channel,
                direction=direction,
            )
            session.add(txn)
            session.flush()

            # Update sliding window
            self.window.add_event(
                account_id=str(txn.account_id),
                amount=txn.amount,
                counterparty=txn.counterparty,
            )

            ctx = RuleContext(
                transaction_id=txn.id,
                account_id=txn.account_id,
                customer_id=cust.id if cust else 0,
                ts=txn.ts,
                amount=txn.amount,
                currency=txn.currency or "USD",
                merchant=txn.merchant,
                counterparty=txn.counterparty,
                country=txn.country,
                channel=txn.channel,
                direction=txn.direction,
                session=session,
            )

            all_hits: list[RuleResult] = []
            for rule in rules:
                hits = rule.evaluate(ctx)
                for hit in hits:
                    # Deduplication check
                    if self.deduplicator:
                        dedup_key = (str(txn.id), hit.rule_id)
                        if self.deduplicator.is_duplicate(dedup_key):
                            log.debug("Dedup: skipping %s for txn %s", hit.rule_id, txn.id)
                            continue

                    ev = dict(hit.evidence_fields or {})
                    ev["rule_hash"] = rule.get_rule_hash()
                    alert = Alert(
                        transaction_id=txn.id,
                        rule_id=hit.rule_id,
                        severity=hit.severity,
                        score=hit.score_delta,
                        reason=hit.reason,
                        evidence_fields=ev,
                        config_hash=config_hash,
                        rules_version=RULES_VERSION,
                        engine_version=ENGINE_VERSION,
                    )
                    session.add(alert)
                    session.flush()

                    alert_data = {
                        "id": alert.id,
                        "transaction_id": txn.id,
                        "rule_id": hit.rule_id,
                        "severity": hit.severity,
                        "score": hit.score_delta,
                        "reason": hit.reason,
                        "created_at": alert.created_at.isoformat() if alert.created_at else None,
                    }
                    created_alerts.append(alert_data)
                    emit_alert_created(alert_data)
                    self.alert_count += 1
                    all_hits.append(hit)

            base = float(cust.base_risk) if cust else base_risk
            score, _ = compute_transaction_risk(
                base, all_hits, max_score=max_score, low_threshold=low_t, medium_threshold=med_t
            )
            txn.risk_score = score
            txn.config_hash = config_hash
            txn.rules_version = RULES_VERSION
            txn.engine_version = ENGINE_VERSION

        self.processed_count += 1
        return created_alerts


class FileStreamConsumer(StreamConsumer):
    """Read transactions from a JSONL file line by line."""

    def __init__(
        self,
        input_path: str | Path,
        processed_path: str | Path | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.input_path = Path(input_path)
        self.processed_path = Path(processed_path) if processed_path else None
        self._committed: list[str] = []

    def consume(self, max_messages: int | None = None) -> None:
        """Read and process each line of the JSONL file."""
        if not self.input_path.exists():
            log.warning("Input file not found: %s", self.input_path)
            return

        count = 0
        with open(self.input_path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("Invalid JSON on line %d, skipping", line_num)
                    continue

                alerts = self.process_message(msg)
                msg_id = str(line_num)
                self.commit(msg_id)

                count += 1
                if max_messages is not None and count >= max_messages:
                    break

        log.info(
            "FileStreamConsumer finished: %d messages, %d alerts",
            self.processed_count,
            self.alert_count,
        )

    def commit(self, message_id: str) -> None:
        self._committed.append(message_id)
        if self.processed_path:
            with open(self.processed_path, "a", encoding="utf-8") as f:
                f.write(f"{message_id}\n")


class RedisStreamConsumer(StreamConsumer):
    """Read transactions from a Redis Stream using consumer groups."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        stream_key: str = "aml:transactions",
        consumer_group: str = "aml-workers",
        consumer_name: str = "worker-1",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        try:
            import redis as redis_lib
        except ImportError as e:
            raise ImportError(
                "redis package required for RedisStreamConsumer. "
                "Install with: poetry add redis"
            ) from e
        self._client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
        self._stream_key = stream_key
        self._consumer_group = consumer_group
        self._consumer_name = consumer_name
        self._ensure_group()

    def _ensure_group(self) -> None:
        """Create consumer group if it doesn't exist."""
        try:
            self._client.xgroup_create(self._stream_key, self._consumer_group, id="0", mkstream=True)
        except Exception:
            pass  # Group already exists

    def consume(self, max_messages: int | None = None) -> None:
        """Read from Redis Stream using XREADGROUP."""
        count = 0
        while True:
            entries = self._client.xreadgroup(
                self._consumer_group,
                self._consumer_name,
                {self._stream_key: ">"},
                count=self.batch_size,
                block=self.poll_interval_ms,
            )
            if not entries:
                if max_messages is not None:
                    break
                continue

            for _stream, messages in entries:
                for msg_id, fields in messages:
                    data_str = fields.get("data", "{}")
                    try:
                        msg = json.loads(data_str)
                    except json.JSONDecodeError:
                        log.warning("Invalid JSON in message %s", msg_id)
                        self.commit(msg_id)
                        continue
                    self.process_message(msg)
                    self.commit(msg_id)
                    count += 1
                    if max_messages is not None and count >= max_messages:
                        return

    def commit(self, message_id: str) -> None:
        self._client.xack(self._stream_key, self._consumer_group, message_id)

    def close(self) -> None:
        self._client.close()

    def stream_info(self) -> dict[str, Any]:
        """Return stream and consumer group info for status reporting."""
        try:
            info = self._client.xinfo_stream(self._stream_key)
            groups = self._client.xinfo_groups(self._stream_key)
            return {
                "stream_key": self._stream_key,
                "length": info.get("length", 0),
                "groups": groups,
            }
        except Exception as e:
            return {"error": str(e)}
