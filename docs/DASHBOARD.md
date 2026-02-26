# AML Monitoring Dashboard

Browser UI for alerts, cases, and SAR reports. Built with Streamlit.

## Run

**Option 1 – With Docker (recommended: API + dashboard in one go)**

Ensure Docker Desktop (or the Docker daemon) is running, then:

```bash
docker compose up -d --build
# Seed data (one-time or after reset): ./scripts/demo.sh
```

Then open **http://localhost:8501** for the dashboard and **http://localhost:8000/docs** for the API.

**Option 2 – Local (API + dashboard on host)**

```bash
# 1) Start the API (required for live alerts/cases)
make serve
# or: poetry run aml serve-api

# 2) In another terminal, start the dashboard
make dashboard
# or: streamlit run scripts/dashboard.py
```

Open **http://localhost:8501**.

**Option 3 – One script (API + dashboard, same terminal)**

If the dashboard "doesn't work" when started from an IDE or remote environment, run everything **in your own terminal** on your machine so that `localhost` is correct:

```bash
cd "/path/to/AML Transaction Monitoring Engine Project"
chmod +x scripts/start_dashboard.sh
./scripts/start_dashboard.sh
```

This starts the API on port 8001 (if not already running), then starts the dashboard on 8501. Open **http://localhost:8501** in your browser. The script uses the dev config (valid high-risk countries) so the API starts without errors.

## Behaviour

- **Theme**: Dark theme (`.streamlit/config.toml`) with custom header and metric styling.
- **Tabs**: Overview (severity chart), Alerts (paginated table), Cases, SAR Report (latest file preview).
- **Data source**: Alerts and cases from the API (`GET /alerts`, `GET /cases`). SAR report from the latest `reports/sar_*.json` file.
- **Alerts pagination**: Previous / Next with configurable page size in the sidebar.
- **When API is down**: Summary and tables show "unavailable"; the dashboard still shows the latest SAR file from disk so you can view report data.
- **Refresh**: Use the sidebar "Refresh data" button to clear cache and refetch. Otherwise data is cached for 60 seconds (configurable).

## Configuration (environment)

| Variable | Default | Purpose |
|----------|---------|--------|
| `AML_DASHBOARD_API` | `http://127.0.0.1:8000` | API base URL |
| `AML_REPORTS_DIR` | `reports` | Directory for SAR JSON/CSV |
| `AML_DASHBOARD_TIMEOUT` | `10` | Request timeout (seconds) |
| `AML_DASHBOARD_CACHE_TTL` | `60` | Cache TTL (seconds) |
| `AML_DASHBOARD_MAX_ALERTS` | `500` | Max alerts fetched from API |
| `AML_DASHBOARD_MAX_CASES` | `200` | Max cases fetched from API |
| `AML_DASHBOARD_SAR_PREVIEW` | `100` | Max SAR alert rows shown in preview |
| `AML_DASHBOARD_ALERTS_PAGE_SIZE` | `50` | Alerts per page in the table (pagination) |

## Stress-test and making it better

- **Many alerts (1000+)**  
  Increase `AML_DASHBOARD_MAX_ALERTS` (e.g. 1000). The API already supports `limit` up to 1000. For very large datasets, consider pagination in the dashboard (e.g. "Next 500") or keeping a cap and linking to the API/OpenAPI for full export.

- **Slow or flaky API**  
  Increase `AML_DASHBOARD_TIMEOUT` (e.g. 20). The dashboard shows a clear message when the API is unreachable and falls back to SAR file only.

- **Fresher data**  
  Lower `AML_DASHBOARD_CACHE_TTL` (e.g. 30) or use "Refresh data" in the sidebar to clear cache on demand.

- **Large SAR files**  
  Lower `AML_DASHBOARD_SAR_PREVIEW` so the preview table stays fast. Full file remains on disk for export/BI.

- **Different API host/port**  
  Set `AML_DASHBOARD_API` or change the "API base URL" in the sidebar.

- **Read-only / no API**  
  Leave the API stopped; the dashboard still shows the latest SAR report from `reports/`.

- **Production hardening**  
  Run Streamlit behind a reverse proxy (e.g. nginx) with HTTPS; restrict who can access the dashboard. Do not expose the API or dashboard publicly without auth.

## Troubleshooting: "Not working" / blank page / connection refused

- **Dashboard or API started from Cursor/IDE**  
  If you started the servers from inside Cursor (or another remote/cloud environment), they may be running on a different machine. Your browser’s `localhost` then never reaches them. **Fix:** Run `./scripts/start_dashboard.sh` in a **local terminal** on your Mac (Terminal.app or iTerm), then open http://localhost:8501 in that same machine’s browser.

- **API fails to start (e.g. config XX/YY)**  
  Use the dev overlay so high-risk countries are valid: `export AML_CONFIG_PATH=config/default.yaml AML_ENV=dev` before starting the API, or use `./scripts/start_dashboard.sh` (it sets these).

- **Dashboard says "unavailable" for alerts/cases**  
  The dashboard talks to the API at `AML_DASHBOARD_API` (default 8000). If you started the API with dev config it’s on port **8001**; set `AML_DASHBOARD_API=http://127.0.0.1:8001` when starting the dashboard, or use `./scripts/start_dashboard.sh` which sets it.
