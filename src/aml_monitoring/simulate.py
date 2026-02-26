"""Simulate near-real-time stream: read file in batches with delay."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from aml_monitoring.config import get_config
from aml_monitoring.ingest import ingest_csv, ingest_jsonl
from aml_monitoring.logging_config import get_logger

logger = get_logger(__name__)


def run_stream_simulation(
    filepath: str | Path,
    config_path: str | None = None,
    delay_seconds: float = 1.0,
    batch_size: int = 10,
) -> None:
    """Read file in chunks, ingest each chunk, then run rules (optional). Delay between chunks."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(str(path))
    cfg = get_config(config_path)
    delay = float(cfg.get("stream_simulate", {}).get("delay_seconds", delay_seconds))
    batch_size = int(cfg.get("stream_simulate", {}).get("batch_size", batch_size))

    if path.suffix.lower() == ".csv":
        _stream_csv(path, delay, batch_size, config_path)
    else:
        _stream_jsonl(path, delay, batch_size, config_path)


def _stream_csv(path: Path, delay: float, batch_size: int, config_path: str | None = None) -> None:
    """Stream CSV in batches: write temp batch file, ingest, delete, sleep."""
    import tempfile

    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        batch: list[dict] = []
        for row in reader:
            batch.append(row)
            if len(batch) >= batch_size:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
                ) as tmp:
                    w = csv.DictWriter(tmp, fieldnames=fieldnames)
                    w.writeheader()
                    w.writerows(batch)
                    tmp_path = tmp.name
                ingest_csv(tmp_path, batch_size=len(batch), config_path=config_path)
                Path(tmp_path).unlink(missing_ok=True)
                logger.info("Ingested batch of %d", len(batch))
                batch = []
                time.sleep(delay)
        if batch:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
            ) as tmp:
                w = csv.DictWriter(tmp, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(batch)
                tmp_path = tmp.name
            ingest_csv(tmp_path, batch_size=len(batch), config_path=config_path)
            Path(tmp_path).unlink(missing_ok=True)
            logger.info("Ingested final batch of %d", len(batch))


def _stream_jsonl(
    path: Path, delay: float, batch_size: int, config_path: str | None = None
) -> None:
    import tempfile

    batch: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                batch.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(batch) >= batch_size:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
                ) as tmp:
                    for obj in batch:
                        tmp.write(json.dumps(obj) + "\n")
                    tmp_path = tmp.name
                ingest_jsonl(tmp_path, batch_size=len(batch), config_path=config_path)
                Path(tmp_path).unlink(missing_ok=True)
                logger.info("Ingested batch of %d", len(batch))
                batch = []
                time.sleep(delay)
    if batch:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as tmp:
            for obj in batch:
                tmp.write(json.dumps(obj) + "\n")
            tmp_path = tmp.name
        ingest_jsonl(tmp_path, batch_size=len(batch), config_path=config_path)
        Path(tmp_path).unlink(missing_ok=True)
        logger.info("Ingested final batch of %d", len(batch))
