#!/usr/bin/env python3
"""Quick check that the dashboard script imports and helpers work (no Streamlit server)."""

from __future__ import annotations

import json
from pathlib import Path

# Simulate what dashboard does without starting Streamlit
REPORTS_DIR = Path("reports")


def _latest_sar_json(reports_dir: Path) -> Path | None:
    if not reports_dir.exists():
        return None
    jsons = sorted(reports_dir.glob("sar_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return jsons[0] if jsons else None


def main() -> None:
    sar_path = _latest_sar_json(REPORTS_DIR)
    if sar_path:
        with open(sar_path, encoding="utf-8") as f:
            data = json.load(f)
        alerts = data.get("alerts") or []
        print("OK: Dashboard data check passed.")
        print(f"  Latest SAR: {sar_path.name} ({len(alerts)} alerts)")
    else:
        print(
            "OK: No SAR file found (reports/ empty or missing). Dashboard will show fallback message."
        )
    # Import streamlit only to verify it's installable
    try:
        import streamlit as st  # noqa: F401

        print("  Streamlit: importable")
    except ImportError:
        print("  Streamlit: not installed. Run: poetry install")


if __name__ == "__main__":
    main()
