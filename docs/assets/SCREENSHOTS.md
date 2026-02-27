# How to capture real dashboard screenshots for GitHub

The README shows three images: **Overview**, **Alerts**, and **Network**. Use this guide to replace the placeholders with real screenshots.

---

## Step-by-step with the real dataset (~100k rows)

Use **`data/real/transactions.csv`** (100k+ rows). The ingest pipeline auto-maps its columns (e.g. `account_id`→`iban_or_acct`, `timestamp`→`ts`, `merchant_name`→`merchant`).

### Step 1 – Go to project root

```bash
cd "/Users/cesco/Downloads/Fintech Projects /AML Transaction Monitoring Engine Project"
```

### Step 2 – (Optional) Fresh database

If you want the dashboard to show **only** this dataset (no leftover synthetic data), start with a clean DB. With `AML_ENV=dev` (Step 3) the DB is `data/aml_dev.db`; without it, `data/aml.db`.

```bash
# Optional: remove existing DB so only real data is loaded
rm -f data/aml.db data/aml_dev.db
```

If you skip this, the real CSV will be **added** to existing data (duplicates skipped by `external_id`).

### Step 3 – Ingest the real CSV and run the pipeline

Use **dev config** so high-risk country placeholders (XX/YY) are replaced with real ISO codes (IR, KP, SY, CU); otherwise the CLI will error.

```bash
export AML_ENV=dev
poetry install
poetry run aml ingest data/real/transactions.csv
poetry run aml build-network
poetry run aml run-rules
poetry run aml generate-reports
```

Ingest may take a minute for 100k rows. Rules and reports will then run on the ingested data.

### Step 4 – Start the API and dashboard

In the same terminal (or a second one):

```bash
./scripts/start_dashboard.sh
```

This starts the API on port **8001** and the dashboard on **8501**. If the script fails (e.g. `gh` or port in use), run manually:

```bash
export AML_ENV=dev AML_DASHBOARD_API=http://127.0.0.1:8001
poetry run aml serve-api &
# wait a few seconds, then:
poetry run streamlit run scripts/dashboard.py --server.port 8501
```

Open in your browser:

- **Dashboard:** http://localhost:8501  
- **API docs:** http://127.0.0.1:8001/docs  

### Step 5 – Capture the three screenshots

| File | What to capture | Where |
|------|-----------------|--------|
| **overview.png** | Overview tab: four metric cards + “Alerts by severity” bar chart. | Stay on **“📈 Overview”**. |
| **alerts.png**   | Alerts tab: table with id, rule_id, severity, status, reason, score, created_at. | Click **“🚨 Alerts”**. |
| **network.png**  | Either **“📋 Cases”** tab or **API docs** with `GET /network/account/{account_id}` visible. | Dashboard → Cases, or open `/docs` and scroll to network. |

Use **`Cmd + Shift + 4`** (macOS) to select the dashboard area; save as `overview.png`, `alerts.png`, `network.png`.

### Step 6 – Save and push

Overwrite the placeholders in the repo:

```bash
# Copy your three PNGs into the project (e.g. from Desktop)
cp ~/Desktop/overview.png docs/assets/
cp ~/Desktop/alerts.png   docs/assets/
cp ~/Desktop/network.png  docs/assets/

git add docs/assets/*.png
git commit -m "Replace dashboard screenshots with real captures (100k dataset)"
git push
```

### Fix: Cases tab has data (for network.png)

If the **Cases** tab shows “No cases”, create one via the API so the third screenshot shows a real row. With the API running on port 8001:

```bash
curl -s -X POST http://127.0.0.1:8001/cases \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev_key" \
  -d '{"alert_ids":[1],"priority":"HIGH","assigned_to":"analyst1","note":"Demo case"}'
```

Then in the dashboard click **“🔄 Refresh data”** (sidebar), open the **“📋 Cases”** tab, take a screenshot, and save it as `network.png` in `docs/assets/`.

---

## Alternative: Docker + demo (synthetic data)

**Option A – Docker (easiest)**

```bash
cd "/Users/cesco/Downloads/Fintech Projects /AML Transaction Monitoring Engine Project"
docker compose up -d --build
./scripts/demo.sh
```

**Option B – Local with synthetic data**

```bash
./scripts/start_dashboard.sh
```

In another terminal:

```bash
poetry run python scripts/generate_synthetic_data.py
poetry run aml ingest data/synthetic/transactions.csv
poetry run aml run-rules
poetry run aml generate-reports
```

Then open **http://localhost:8501** (dashboard) and **http://localhost:8000/docs** or **http://127.0.0.1:8001/docs** (API docs).

---

## 2. What to capture

| File | What to capture | Where |
|------|-----------------|--------|
| **overview.png** | Dashboard **Overview** tab: the four metric cards (Total alerts, High severity, Cases, Latest SAR) and the “Alerts by severity” bar chart. | http://localhost:8501 → leave on the first tab “📈 Overview”. |
| **alerts.png** | Dashboard **Alerts** tab: the paginated table with columns id, rule_id, severity, status, reason, score, created_at. | http://localhost:8501 → click “🚨 Alerts”. |
| **network.png** | The dashboard has no “Network” tab. Use either: **(A)** **Cases** tab (table of cases: id, status, priority, assigned_to, created_at), or **(B)** **API docs** page with the `GET /network/account/{account_id}` endpoint visible. | (A) http://localhost:8501 → “📋 Cases”. (B) http://localhost:8000/docs (or 8001) → scroll to the network endpoint. |

---

## 3. How to capture (macOS)

- **Full window:** `Cmd + Shift + 3` → paste into Preview, crop to the dashboard content, then export as PNG.
- **Selected area:** `Cmd + Shift + 4` → drag to select the dashboard area → saves PNG to Desktop. Move/rename into the project.
- **Browser screenshot extensions** (e.g. “Full Page” or “Visible”) can capture the main content area; crop to remove browser chrome if you want a cleaner look.

---

## 4. Where to put the files

Save (or overwrite) the three PNGs here:

- `docs/assets/overview.png`
- `docs/assets/alerts.png`
- `docs/assets/network.png`

Then commit and push:

```bash
git add docs/assets/*.png
git commit -m "Replace dashboard screenshots with real captures"
git push
```

GitHub will then show the real screenshots in the README.
