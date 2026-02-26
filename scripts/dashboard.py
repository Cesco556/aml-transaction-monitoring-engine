#!/usr/bin/env python3
"""
AML Monitoring Dashboard – view alerts, cases, and SAR reports in the browser.
Run: streamlit run scripts/dashboard.py
Requires the API to be running (e.g. make serve) unless using report-only fallback.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# --- Config (env + sidebar) ---
DEFAULT_API_BASE = os.environ.get("AML_DASHBOARD_API", "http://127.0.0.1:8000")
DEFAULT_REPORTS_DIR = os.environ.get("AML_REPORTS_DIR", "reports")
REQUEST_TIMEOUT = int(os.environ.get("AML_DASHBOARD_TIMEOUT", "10"))
CACHE_TTL = int(os.environ.get("AML_DASHBOARD_CACHE_TTL", "60"))
MAX_ALERTS = int(os.environ.get("AML_DASHBOARD_MAX_ALERTS", "500"))
MAX_CASES = int(os.environ.get("AML_DASHBOARD_MAX_CASES", "200"))
SAR_PREVIEW_ROWS = int(os.environ.get("AML_DASHBOARD_SAR_PREVIEW", "100"))
ALERTS_PAGE_SIZE = int(os.environ.get("AML_DASHBOARD_ALERTS_PAGE_SIZE", "50"))


def _fetch_json(url: str, timeout: int = REQUEST_TIMEOUT) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


@st.cache_data(ttl=CACHE_TTL)
def _cached_alerts(base: str, limit: int, severity: str | None) -> tuple[list[dict], str | None]:
    try:
        path = f"{base.rstrip('/')}/alerts?limit={limit}"
        if severity:
            path += f"&severity={severity}"
        data = _fetch_json(path, timeout=REQUEST_TIMEOUT)
        return (data if isinstance(data, list) else [], None)
    except Exception as e:
        return ([], str(e))


@st.cache_data(ttl=CACHE_TTL)
def _cached_cases(base: str, limit: int) -> tuple[list[dict], str | None]:
    try:
        data = _fetch_json(f"{base.rstrip('/')}/cases?limit={limit}", timeout=REQUEST_TIMEOUT)
        return (data if isinstance(data, list) else [], None)
    except Exception as e:
        return ([], str(e))


def _latest_sar_json(reports_dir: Path) -> Path | None:
    if not reports_dir.exists():
        return None
    jsons = sorted(reports_dir.glob("sar_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return jsons[0] if jsons else None


def _load_sar_preview(path: Path, max_rows: int) -> tuple[list[dict], str | None]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        alerts = data.get("alerts") or []
        return (alerts[:max_rows], None)
    except Exception as e:
        return ([], str(e))


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        /* Metric cards */
        [data-testid="stMetricValue"] { font-size: 1.8rem; font-weight: 600; }
        /* Tighter spacing */
        .block-container { padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1400px; }
        /* Header strip */
        .aml-header { padding: 0.5rem 0 1rem 0; border-bottom: 1px solid rgba(250,250,250,0.1); margin-bottom: 1rem; }
        .aml-header h1 { margin: 0; font-size: 1.75rem; }
        .aml-subtitle { color: rgba(250,250,250,0.7); font-size: 0.95rem; margin-top: 0.25rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="AML Monitoring", page_icon="🛡️", layout="wide", initial_sidebar_state="expanded"
    )
    _inject_css()

    st.markdown(
        '<div class="aml-header">'
        "<h1>🛡️ AML Transaction Monitoring</h1>"
        '<p class="aml-subtitle">Alerts, cases & SAR reports · Live from API and reports</p>'
        "</div>",
        unsafe_allow_html=True,
    )

    reports_dir = Path(DEFAULT_REPORTS_DIR)
    with st.sidebar:
        st.markdown("### ⚙️ Settings")
        api_base = st.text_input(
            "API base URL",
            value=DEFAULT_API_BASE,
            help="e.g. http://127.0.0.1:8000",
            label_visibility="collapsed",
        )
        st.markdown("**Filters**")
        severity_filter = st.selectbox(
            "Alert severity",
            ["all", "high", "medium", "low"],
            index=0,
            label_visibility="collapsed",
        )
        page_size = st.number_input(
            "Alerts per page", min_value=10, max_value=200, value=ALERTS_PAGE_SIZE, step=10
        )
        if st.button("🔄 Refresh data", use_container_width=True):
            _cached_alerts.clear()
            _cached_cases.clear()
            if "alerts_page" in st.session_state:
                del st.session_state["alerts_page"]
            st.rerun()
        st.caption(f"Cache {CACHE_TTL}s · Max {MAX_ALERTS} alerts")

    severity = None if severity_filter == "all" else severity_filter

    alerts_data, alerts_err = _cached_alerts(api_base, MAX_ALERTS, severity)
    cases_data, cases_err = _cached_cases(api_base, MAX_CASES)
    api_ok = not (alerts_err or cases_err)

    if not api_ok:
        st.warning(
            "⚠️ API unreachable. Showing report files only. Start the API with `make serve` or run the demo."
        )
        if alerts_err:
            st.caption(f"Alerts: {alerts_err}")
        if cases_err:
            st.caption(f"Cases: {cases_err}")

    # --- Metrics ---
    high = sum(1 for a in alerts_data if (a.get("severity") or "").lower() == "high")
    sar_path = _latest_sar_json(reports_dir)
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total alerts", len(alerts_data), help="From API" if api_ok else "N/A")
    with col2:
        st.metric("High severity", high, help="Requires review")
    with col3:
        st.metric("Cases", len(cases_data), help="From API" if api_ok else "N/A")
    with col4:
        st.metric("Latest SAR", sar_path.name if sar_path else "—", help="From reports/")
    st.divider()

    # --- Tabs: Overview | Alerts | Cases | SAR ---
    tab_overview, tab_alerts, tab_cases, tab_sar = st.tabs(
        ["📈 Overview", "🚨 Alerts", "📋 Cases", "📄 SAR Report"]
    )

    with tab_overview:
        if alerts_data:
            severity_counts: dict[str, int] = {}
            for a in alerts_data:
                sev = (a.get("severity") or "unknown").lower()
                severity_counts[sev] = severity_counts.get(sev, 0) + 1
            chart_df = pd.DataFrame({"count": severity_counts}).sort_index()
            if not chart_df.empty:
                st.subheader("Alerts by severity")
                st.bar_chart(chart_df, width="stretch")
        else:
            st.info("No alert data yet. Run ingest and run-rules, or check API connection.")

    with tab_alerts:
        if alerts_data:
            rows = []
            for a in alerts_data:
                rows.append(
                    {
                        "id": a.get("id"),
                        "rule_id": a.get("rule_id"),
                        "severity": a.get("severity"),
                        "status": a.get("status"),
                        "reason": (a.get("reason") or "")[:80],
                        "score": a.get("score"),
                        "created_at": str(a.get("created_at", ""))[:19],
                    }
                )
            total = len(rows)
            if "alerts_page" not in st.session_state:
                st.session_state["alerts_page"] = 0
            max_page = max(0, (total - 1) // page_size)
            st.session_state["alerts_page"] = min(st.session_state["alerts_page"], max_page)
            page = st.session_state["alerts_page"]
            start = page * page_size
            end = min(start + page_size, total)
            page_rows = rows[start:end]
            st.dataframe(page_rows, width="stretch", hide_index=True)
            c1, c2, c3 = st.columns([1, 2, 1])
            with c2:
                st.caption(f"Page {page + 1} of {max_page + 1} · Rows {start + 1}–{end} of {total}")
                prev, next_ = st.columns(2)
                with prev:
                    if st.button(
                        "← Previous",
                        disabled=(page <= 0),
                        use_container_width=True,
                        key="prev_alert",
                    ):
                        st.session_state["alerts_page"] = page - 1
                        st.rerun()
                with next_:
                    if st.button(
                        "Next →",
                        disabled=(page >= max_page),
                        use_container_width=True,
                        key="next_alert",
                    ):
                        st.session_state["alerts_page"] = page + 1
                        st.rerun()
            if total >= MAX_ALERTS:
                st.caption(f"Showing first {MAX_ALERTS} alerts. Use API for full export.")
        else:
            st.info("No alerts. Run ingest and run-rules, or check API connection.")

    with tab_cases:
        if cases_data:
            rows = []
            for c in cases_data:
                rows.append(
                    {
                        "id": c.get("id"),
                        "status": c.get("status"),
                        "priority": c.get("priority"),
                        "assigned_to": c.get("assigned_to") or "—",
                        "created_at": str(c.get("created_at", ""))[:19],
                    }
                )
            st.dataframe(rows, width="stretch", hide_index=True)
            if len(cases_data) >= MAX_CASES:
                st.caption(f"Showing first {MAX_CASES} cases.")
        else:
            st.info("No cases. Create via API (POST /cases) or run the demo script.")

    with tab_sar:
        sar_path_tab = _latest_sar_json(reports_dir)
        if sar_path_tab:
            preview, sar_err = _load_sar_preview(sar_path_tab, SAR_PREVIEW_ROWS)
            if sar_err:
                st.error(f"Could not load SAR file: {sar_err}")
            elif preview:
                st.caption(f"Preview from {sar_path_tab.name} (first {len(preview)} alerts)")
                st.dataframe(preview, width="stretch", hide_index=True)
            else:
                st.caption(f"File {sar_path_tab.name} has no alerts array.")
        else:
            st.info(f"No SAR JSON in {reports_dir}. Run `aml generate-reports`.")

    st.divider()
    st.caption("AML Monitoring · Data from API and reports/")


if __name__ == "__main__":
    main()
