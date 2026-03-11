"""Stream producers: write transactions to Redis Streams or JSONL files."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class StreamProducer(ABC):
    """Abstract base for stream producers."""

    @abstractmethod
    def publish(self, message: dict[str, Any]) -> str | None:
        """Publish a single transaction message. Returns message ID if available."""
        ...

    def publish_batch(self, messages: list[dict[str, Any]]) -> list[str | None]:
        """Publish multiple messages. Default: iterate publish()."""
        return [self.publish(m) for m in messages]

    def close(self) -> None:
        """Clean up resources."""
        pass


class FileStreamProducer(StreamProducer):
    """Append transaction JSON to a JSONL file."""

    def __init__(self, output_path: str | Path) -> None:
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._line_count = 0

    def publish(self, message: dict[str, Any]) -> str | None:
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(message, default=str) + "\n")
        self._line_count += 1
        msg_id = str(self._line_count)
        log.debug("Published message %s to %s", msg_id, self.output_path)
        return msg_id


class RedisStreamProducer(StreamProducer):
    """Publish transactions to a Redis Stream via XADD."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        stream_key: str = "aml:transactions",
    ) -> None:
        try:
            import redis as redis_lib
        except ImportError as e:
            raise ImportError(
                "redis package required for RedisStreamProducer. "
                "Install with: poetry add redis"
            ) from e
        self._client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
        self._stream_key = stream_key

    def publish(self, message: dict[str, Any]) -> str | None:
        payload = {"data": json.dumps(message, default=str)}
        msg_id = self._client.xadd(self._stream_key, payload)
        log.debug("Published %s to %s", msg_id, self._stream_key)
        return msg_id

    def close(self) -> None:
        self._client.close()
