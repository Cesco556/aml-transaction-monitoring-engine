# AML Transaction Monitoring Engine

> Enterprise-grade Anti-Money Laundering platform with hybrid detection (rules + ML), real-time streaming, network intelligence, and compliance reporting.

[![Tests](https://img.shields.io/badge/tests-368%20passed-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()

---

## Why This Exists

Banks and fintechs need to detect money laundering, terrorist financing, and sanctions violations in real-time. Commercial solutions (Actimize, Featurespace, Feedzai) cost millions. This is an open-source alternative that covers the full pipeline — from transaction ingestion to regulatory filing.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        API Gateway (FastAPI)                      │
│          Rate-limited │ CORS │ JWT/API Key Auth │ WebSocket       │
├──────────┬───────────┬───────────┬───────────┬──────────────────┤
│  Rules   │    ML     │ Sanctions │ Network   │    Reporting     │
│  Engine  │  Scoring  │ Screening │ Analysis  │   & Compliance   │
├──────────┴───────────┴───────────┴───────────┴──────────────────┤
│              Streaming Layer (Redis / File-based)                 │
│         Consumer │ Producer │ WebSocket Alerts │ Dedup            │
├──────────────────────────────────────────────────────────────────┤
│                    PostgreSQL / SQLite                            │
│          Alembic Migrations │ Audit Chain │ Full Traceability     │
└──────────────────────────────────────────────────────────────────┘
```

## Key Features

### 🔍 Hybrid Detection Engine
- **8 configurable rules**: High Value, Rapid Velocity, Geo Mismatch, Structuring/Smurfing, Sanctions Keyword, High-Risk Country, Network Ring, ML Anomaly
- **Isolation Forest ML**: Unsupervised anomaly detection with 7 behavioral features (velocity, amount z-score, counterparty diversity, time-of-day patterns)
- **Pluggable architecture**: Add custom rules by extending `BaseRule`

### 🎯 Advanced Scoring
- Weighted severity multipliers (critical 2.0x → low 0.5x)
- Temporal decay (recent alerts weigh more)
- Customer risk profiles from alert history
- Scoring profiles: conservative / balanced / aggressive

### 🛡️ Sanctions & PEP Screening
- **4 matching algorithms**: Exact, Levenshtein, Jaro-Winkler, Phonetic (Soundex/Metaphone)
- **OFAC SDN list parser** with auto-update support
- **PEP screening** with country filtering and risk levels
- Name normalization: handles "Mohammed" vs "Muhammad", "Ltd" vs "Limited", unicode
- Configurable match thresholds with confidence scores in evidence

### 🌐 Network Intelligence
- **Graph analysis**: NetworkX-powered transaction graphs with multi-hop traversal
- **Community detection**: Louvain and label propagation algorithms
- **Money flow tracing**: Hierarchical FlowTree showing fund movement paths
- **Ownership analysis**: Detects accounts controlled by the same entity
- **Visualization exports**: D3.js and Cytoscape.js compatible formats

### ⚡ Real-time Streaming
- Stream consumer framework (Redis Streams + file-based)
- WebSocket alert push (`/ws/alerts`)
- Sliding window aggregations for streaming rules
- Alert deduplication with configurable TTL
- Consumer groups for horizontal scaling

### 📊 Compliance Reporting
- **FinCEN SAR**: BSA E-Filing format (XML + JSON), auto-generated narratives
- **PDF reports**: Professional investigation reports with 8 sections
- **Regulatory timelines**: FinCEN (30/60d), UK FCA (15/30d), EU AMLD (30/45d)
- **Dashboard KPIs**: Alert volumes, SAR conversion rate, false positive rate, investigation time
- **Audit export**: Examiner-ready ZIP with hash chain verification

### 🔒 Security
- Rate limiting (100 reads/min, 20 writes/min)
- CORS with configurable origins
- Security headers (CSP, X-Frame-Options, X-Content-Type-Options)
- API key auth with scoped permissions (read_only / read_write)
- Request size limits
- Audit trail with tamper-resistant hash chain

### 🏗️ Production Infrastructure
- **Docker Compose**: API + Dashboard + Worker + Postgres + Redis
- **Cursor-based pagination** on all list endpoints
- **Health checks**: `/health`, `/ready`, `/metrics`
- **Alembic migrations** for schema versioning
- **Idempotent ingest** with deterministic `external_id`

---

## Quick Start

### Prerequisites
- Python 3.11+
- [Poetry](https://python-poetry.org/)

### Install & Run

```bash
# Clone
git clone https://github.com/Cesco556/aml-transaction-monitoring-engine.git
cd aml-transaction-monitoring-engine

# Install
poetry install

# Generate synthetic data
poetry run aml synthetic --count 1000

# Ingest transactions
poetry run aml ingest data/synthetic/transactions.csv

# Run detection rules
poetry run aml run-rules

# Train ML model
poetry run aml train-ml

# Generate reports
poetry run aml generate-reports

# Start API
poetry run uvicorn aml_monitoring.api:app --reload

# Start dashboard
poetry run streamlit run scripts/dashboard.py
```

### Docker (Full Stack)

```bash
docker compose up -d --build
# API:       http://localhost:8000
# Dashboard: http://localhost:8501
# Postgres:  localhost:5432
# Redis:     localhost:6379
```

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `aml ingest FILE` | Ingest transactions from CSV/JSONL |
| `aml run-rules` | Run all detection rules |
| `aml train-ml` | Train ML anomaly detection model |
| `aml generate-reports` | Generate SAR-style reports |
| `aml reproduce-run CID` | Export full run bundle by correlation_id |
| `aml screen-name "NAME"` | Screen a name against sanctions + PEP lists |
| `aml load-sanctions PATH` | Load a sanctions list file |
| `aml sanctions-status` | Show loaded lists and entry counts |
| `aml stream-consume` | Start real-time stream consumer |
| `aml stream-produce FILE` | Publish transactions to stream |
| `aml network-analyze` | Run community detection on transaction graph |
| `aml network-export FORMAT` | Export graph (d3 / cytoscape) |
| `aml report-kpis` | Print dashboard KPIs |
| `aml report-sar CASE_ID` | Generate FinCEN SAR for a case |
| `aml report-pdf CASE_ID` | Generate PDF investigation report |
| `aml report-audit` | Generate audit export ZIP |
| `aml report-overdue` | List cases past filing deadline |

---

## API Endpoints

### Core
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Liveness check |
| GET | `/ready` | Readiness (DB + ML model) |
| GET | `/metrics` | System metrics and counts |
| POST | `/score` | Score a single transaction |
| GET | `/alerts` | List alerts (paginated) |
| PATCH | `/alerts/{id}` | Update alert status/disposition |
| GET | `/transactions/{id}` | Get transaction with alerts |

### Cases
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/cases` | Create investigation case |
| GET | `/cases` | List cases (paginated) |
| PATCH | `/cases/{id}` | Update case status |
| POST | `/cases/{id}/notes` | Add case note |

### Network
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/network/account/{id}` | Account edges and ring signal |
| GET | `/network/graph` | Subgraph around account (D3 format) |
| GET | `/network/communities` | Community detection results |
| GET | `/network/path` | Find paths between accounts |
| GET | `/network/flow` | Trace money flow from account |

### Reports
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/reports/kpis` | Dashboard KPIs |
| GET | `/reports/overdue` | Overdue cases |
| GET | `/reports/timeline-metrics` | Filing timeline stats |
| POST | `/reports/sar/{case_id}` | Generate FinCEN SAR |
| POST | `/reports/pdf/{case_id}` | Generate PDF report |
| POST | `/reports/audit-export` | Generate audit ZIP |

### Streaming
| Method | Endpoint | Description |
|--------|----------|-------------|
| WS | `/ws/alerts` | Real-time alert notifications |

---

## Project Structure

```
src/aml_monitoring/
├── api.py                  # FastAPI application
├── auth.py                 # API key authentication & scoping
├── security.py             # Rate limiting, CORS, security headers
├── config.py               # YAML config + env override
├── db.py                   # SQLAlchemy engine + audit chain
├── models.py               # ORM models
├── schemas.py              # Pydantic schemas
├── scoring.py              # Risk scoring (v2: weighted, decay, profiles)
├── pagination.py           # Cursor-based pagination
│
├── ingest/                 # Transaction ingestion
│   ├── csv_ingest.py       # CSV ingestion with column mapping
│   ├── jsonl_ingest.py     # JSONL ingestion
│   └── _idempotency.py     # Deterministic external_id
│
├── rules/                  # Detection rules
│   ├── base.py             # BaseRule abstract class
│   ├── high_value.py       # High-value transaction
│   ├── rapid_velocity.py   # N+ transactions in T minutes
│   ├── geo_mismatch.py     # Geographic anomalies
│   ├── structuring_smurfing.py  # Structuring detection
│   ├── sanctions_keyword.py     # Keyword matching
│   ├── sanctions_screening.py   # Fuzzy sanctions + PEP
│   ├── network_ring.py     # Ring pattern detection
│   └── ml_anomaly.py       # ML-based anomaly detection
│
├── ml/                     # Machine learning
│   ├── features.py         # Feature engineering (7 features)
│   └── anomaly.py          # Isolation Forest training/scoring
│
├── sanctions/              # Sanctions screening
│   ├── matching.py         # Fuzzy matching (4 algorithms)
│   ├── lists.py            # Sanctions list management
│   ├── ofac.py             # OFAC SDN parser
│   └── pep.py              # PEP screening
│
├── network/                # Network intelligence
│   ├── graph.py            # NetworkX graph building
│   ├── communities.py      # Community detection
│   ├── paths.py            # Path analysis & money flow
│   ├── ownership.py        # Beneficiary ownership
│   └── export.py           # D3/Cytoscape export
│
├── streaming/              # Real-time processing
│   ├── consumer.py         # Stream consumers (Redis/File)
│   ├── producer.py         # Stream producers
│   ├── websocket.py        # WebSocket alert push
│   ├── events.py           # Alert event bus
│   ├── windows.py          # Sliding window aggregations
│   └── dedup.py            # Alert deduplication
│
├── reporting/              # Compliance reporting
│   ├── sar_fincen.py       # FinCEN SAR (XML/JSON)
│   ├── pdf_report.py       # PDF investigation reports
│   ├── timelines.py        # Regulatory deadline tracking
│   ├── kpis.py             # Dashboard KPIs
│   └── audit_export.py     # Examiner audit packages
│
└── cli.py                  # Typer CLI (20+ commands)

tests/                      # 368 tests
├── test_rules.py
├── test_scoring_v2.py
├── test_ml.py
├── test_sanctions.py
├── test_streaming.py
├── test_network_intelligence.py
├── test_reporting_compliance.py
├── test_security.py
├── test_infrastructure.py
├── test_integration.py
└── ...
```

---

## Configuration

All settings in `config/default.yaml` with environment variable overrides (`AML_*`):

```yaml
rules:          # Enable/disable rules, set thresholds
scoring:        # Weights, decay, profiles
ml:             # Isolation Forest parameters
sanctions:      # Match thresholds, list paths
streaming:      # Redis/file backend, dedup window
reporting:      # SAR regulation, PDF output, audit settings
security:       # CORS origins, rate limits, headers
```

See [config/default.yaml](config/default.yaml) for all options.

---

## Governance & Audit

- **[Model Risk Management](docs/GOVERNANCE/MRM.md)** — Model validation and change control
- **[Tuning Playbook](docs/GOVERNANCE/TUNING.md)** — Rule threshold tuning methodology
- **[Data Quality](docs/GOVERNANCE/DATA_QUALITY.md)** — Data quality monitoring
- **[Audit Playbook](docs/GOVERNANCE/AUDIT_PLAYBOOK.md)** — Examiner review procedures
- **[Architecture](docs/ARCHITECTURE.md)** — System design documentation

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI, Uvicorn |
| Database | PostgreSQL / SQLite, SQLAlchemy 2.x, Alembic |
| ML | scikit-learn (Isolation Forest), pandas |
| Matching | rapidfuzz, jellyfish |
| Graph | NetworkX |
| Streaming | Redis Streams (optional) |
| PDF | fpdf2 |
| Dashboard | Streamlit |
| Testing | pytest (368 tests) |
| Containerization | Docker, Docker Compose |

---

## License

MIT

---

Built by [Francesco O. Ojoko](https://github.com/Cesco556) — MSc Cybersecurity, Robert Gordon University
