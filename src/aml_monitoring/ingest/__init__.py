"""Ingest modules for CSV and JSONL."""

from aml_monitoring.ingest.csv_ingest import ingest_csv
from aml_monitoring.ingest.jsonl_ingest import ingest_jsonl

__all__ = ["ingest_csv", "ingest_jsonl"]
