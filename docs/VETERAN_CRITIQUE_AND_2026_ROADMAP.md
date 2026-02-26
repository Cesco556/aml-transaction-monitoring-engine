# Veteran Critique & 2026 Roadmap: AML Transaction Monitoring Engine

**Perspective:** A critic with decades of experience designing AML systems who only transacts with systems that **actually solve problems and deliver analysis**—not documentation theatre.  
**Method:** (1) Deep codebase critique to find hidden weaknesses; (2) Definition of what a 2026-grade system should be; (3) Step-by-step plan per industry requirements; (4) Web research for best practices and standards; (5) A single, best-for-this-project step-by-step roadmap.

---

## Part 1 — Veteran Critic View: Does This Engine Actually Solve and Analyse?

### What “solving” means here

- **Solves:** Produces **actionable, timely, well-explained** alerts that lead to triage, disposition, and (where appropriate) SARs. The chain from raw data → risk decision → human action → regulatory outcome is complete and auditable.
- **Analyses:** Surfaces **risk at the right level** (transaction, customer, network), with **explainability**, **data quality visibility**, and **tuning evidence** so the institution can show effectiveness, not just “we run rules.”

### Verdict from that lens

The engine **partially** solves and analyses. It has a solid foundation (traceability, idempotency, rules, scoring, cases, disposition, auth, correlation_id, reproduce bundle) but **critical gaps** remain so that an examiner or a 50-year veteran would say: “You cannot yet demonstrate **effectiveness** or **risk-based calibration** in a 2025/2026 supervisory conversation.”

---

## Part 2 — Hidden Weaknesses (Beyond the Obvious Gaps)

These are issues that a veteran would flag after living with such systems in production.

### 2.1 Data quality is invisible

- **Evidence:** Ingest silently **skips** bad rows (`except (ValueError, KeyError): continue` in csv_ingest and jsonl_ingest). No count of rejected rows, no rejection reason, no feed into a data-quality dashboard or audit.
- **Impact:** Regulators (FATF effectiveness, MAS/FCA guidance) expect “understanding of data limitations.” You cannot prove what was excluded or why; reproducibility is incomplete.
- **Fix principle:** Every ingest must produce **data quality metrics** (rows_read, rows_inserted, rows_rejected, rejection_reasons or codes). Persist in AuditLog or a dedicated table; expose via API/report.

### 2.2 Rules are not tunable or explainable in a governance sense

- **Evidence:** Thresholds live in YAML; there is no **per-rule performance** (hits, false positive rate, conversion to SAR). No link from “we changed threshold” to “before/after alert volume and quality.”
- **Impact:** FATF and supervisors expect “regular review of system configurations, detection rules, and threshold settings” and “well-calibrated frameworks.” You cannot show calibration or tuning impact.
- **Fix principle:** Store rule_id + threshold snapshot in audit; add a **rule performance report** (alerts per rule, disposition breakdown, optional SAR count). Document rule version and threshold in every alert’s evidence or details.

### 2.3 Scoring is additive and uncalibrated

- **Evidence:** `compute_transaction_risk` is base_risk + sum(score_delta); bands are fixed (33/66). No customer segmentation, no link to historical hit rates or risk appetite.
- **Impact:** “Risk-based” in 2026 means proportionality and calibration. A single global band and additive deltas do not demonstrate calibration.
- **Fix principle:** Introduce at least **customer/segment base_risk** (or segment-specific bands); document scoring methodology; optionally store score components for explainability.

### 2.4 No SAR timeliness or usefulness measure

- **Evidence:** Reporting produces files; there is no “alert created → disposition → SAR filed” timeline, no metric for “time to disposition” or “time to SAR.”
- **Impact:** FATF 2025 methodology stresses that SARs must be **timely and useful**. The system does not measure or report on that.
- **Fix principle:** Add timestamps (alert created, disposition updated, optional “SAR filed”); report on average time to disposition and (if applicable) to SAR.

### 2.5 Entity and network are underused

- **Evidence:** `RelationshipEdge` and Case exist, but **rules do not** consume relationship or network features. Counterparty is still a string; no entity-level risk score or network-based rule.
- **Impact:** Industry and research (MAS, HKMA, network analytics literature) expect entity-centric and network-aware monitoring. The data model allows it; the detection logic does not.
- **Fix principle:** At least one rule or score component that uses `RelationshipEdge` or counterparty clustering; one API or report that aggregates by entity/network.

### 2.6 Rules version is not code-backed

- **Evidence:** `RULES_VERSION` is a single string in `__init__.py`; no per-rule version or hash of rule logic in audit/details.
- **Impact:** Reproducibility and model risk management require “which exact logic ran.” A single global version is weak evidence.
- **Fix principle:** Per-rule version or content hash in config/audit; document mapping from version to code/deploy.

### 2.7 Failure modes and backpressure

- **Evidence:** `run_rules` loads all transactions in one pass; no chunking, no resume. Large DB can cause memory pressure or long-running transactions. Ingest has no dead-letter path for repeated failures.
- **Impact:** In production, large volumes and failures are the norm. The system does not yet handle scale or partial failure gracefully.
- **Fix principle:** Chunked run_rules (e.g. by transaction id range) with checkpoint and audit per chunk; optional dead-letter or retry queue for ingest.

### 2.8 Sanctions and list management are primitive

- **Evidence:** Sanctions rule uses a static keyword list in config; no list versioning, no “list effective date,” no separate list entity.
- **Impact:** Regulators expect sanctioned-party lists to be managed, versioned, and auditable. Keywords in YAML are not a list management system.
- **Fix principle:** Introduce list version and effective date; audit which list version was used for each run; document in RULE.md.

### 2.9 High-risk country list is placeholder

- **Evidence:** `config/default.yaml` has `countries: [XX, YY]` with comment “placeholder; replace with ISO codes.”
- **Impact:** In production, this would either match nothing or be wrong. A veteran would treat this as “detection not actually configured.”
- **Fix principle:** Document that XX/YY must be replaced; add a startup or config validation that fails or warns if high_risk_country list is placeholder; consider sourcing from a canonical source (e.g. FATF list).

### 2.10 API key identity is not fine-grained

- **Evidence:** `require_api_key` returns a single actor name per key; no role, no scope (e.g. “can only PATCH alerts for assigned cases”).
- **Impact:** Least privilege and audit require “who can do what.” Today it’s “any valid key can do everything.”
- **Fix principle:** Document limitation; later add scopes or roles and enforce in endpoints (e.g. case assignee can PATCH only their cases).

---

## Part 3 — What a 2026 System Should Be (Industry Requirements)

Synthesised from FATF 2025 methodology, EU AMLD6/AMLR, MAS/FCA-style guidance, and model risk / data quality expectations.

1. **Effectiveness over formality**  
   Policies and systems are judged on **outcomes**: timely, useful SARs; appropriate risk-based calibration; reduced false positives where possible; clear data quality and limitations.

2. **Risk-based and proportional**  
   Controls and monitoring intensity vary by customer/segment risk; thresholds and rules are **calibrated** to the business and regularly reviewed with evidence.

3. **Fully traceable and reproducible**  
   Every decision (alert, score, disposition) is tied to a **run/request** (correlation_id), **actor**, **config/rules version**, and **data scope**. Reproducibility bundles (e.g. by correlation_id) support audit and validation.

4. **Data quality is visible and auditable**  
   Ingest and processing report **rejected rows and reasons**; data quality metrics are stored and reportable; limitations are documented and available to compliance.

5. **Rule/model governance**  
   Rules have **versions and tuning history**; threshold and logic changes are documented and linked to before/after performance; model risk artefacts (methodology, validation, limitations) exist where applicable.

6. **Operational workflow**  
   Alerts are **triaged, assigned, dispositioned** (false positive, escalate, SAR); **cases** group alerts and carry state and assignee; **timeliness** (e.g. time to disposition) is measured and reported.

7. **Entity and network awareness**  
   Risk is considered at **entity and network** level where relevant; at least one detection or report uses relationships or clustering; entity-level risk view is available for high-risk customers.

8. **Secure and identity-bound**  
   API and sensitive actions are **authenticated**; actor is derived from **identity** (not client-supplied); roles/scopes support least privilege.

9. **Production-grade operations**  
   **Versioned schema migrations** (e.g. Alembic for Postgres); chunked/batch processing and clear failure handling; no silent data loss (rejects are recorded).

10. **List and sanctions discipline**  
    Sanctions and high-risk lists are **versioned**, dated, and auditable; which list version was used in each run is recorded.

---

## Part 4 — What Needs to Be Done Step by Step (Industry-Aligned)

Ordered so each step is buildable on the current repo and moves toward the 2026 picture.

| Step | What | Why (industry) |
|------|------|----------------|
| 1 | **Data quality visibility** | FATF/MAS “data limitations”; no silent drops. |
| 2 | **Rule performance and tuning evidence** | Calibration and “regular review of rules/thresholds.” |
| 3 | **SAR/disposition timeliness metrics** | “Timely and useful” SARs. |
| 4 | **Per-rule version / code-backed versioning** | Reproducibility and model risk. |
| 5 | **Scoring methodology doc + optional segment bands** | Risk-based proportionality. |
| 6 | **One network/entity-aware rule or report** | Entity-centric and network analytics. |
| 7 | **Chunked run_rules + failure handling** | Scale and production resilience. |
| 8 | **List versioning (sanctions / high-risk)** | Auditable list usage. |
| 9 | **Config validation (e.g. placeholder lists)** | “Detection actually configured.” |
| 10 | **Roles/scopes for API (optional)** | Least privilege and audit. |

---

## Part 5 — Web Research Synthesis (Best for This Project)

Sources used: FATF 2025 evaluation methodology, EU AMLD6/AMLR timelines, MAS AML/CFT transaction monitoring guidance, FCA good/poor practice, Deloitte/Google/OCC on calibration and model risk, Treasury OIG on SAR data quality, network/entity risk literature.

### 5.1 FATF and effectiveness

- **2025 methodology** stresses **effectiveness**: SARs timely and useful; transaction monitoring **implemented and effective in practice**; risk-based, proportional controls.
- **Implication:** The engine must support **evidence** of effectiveness (metrics, tuning, data quality), not only “we have rules and cases.”

### 5.2 EU AMLD6 / AMLR

- **Timeline:** AMLD6 from July 2025; AMLR (single rulebook) from July 2025 (limited) and July 2027 (full). Lower thresholds, crypto in scope, **ongoing monitoring** (e.g. CDD refresh periods).
- **Implication:** Design for **ongoing monitoring** and **customer/entity view**; keep thresholds and triggers configurable and documented.

### 5.3 Governance and calibration

- **MAS / FCA:** Well-calibrated frameworks; regular review of rules and thresholds; competent staff; **data quality and legacy constraints** understood; **rule performance** and tuning.
- **Deloitte / Google:** Calibration by segment; threshold tuning; model governance artefacts (methodology, tuning, validation); **documentation** as first line of defense.
- **Implication:** Add **rule performance reporting**, **data quality reporting**, and **scoring methodology documentation**; treat rules as tunable and document changes.

### 5.4 Data quality and SAR quality

- **Treasury OIG:** Many SARs had missing/incorrect data; causes include poor instructions and data entry. **Data quality controls** are central.
- **Implication:** **Never silently drop** input rows; record rejects and reasons; expose data quality in audit and reports.

### 5.5 Entity and network

- **Research / MAS:** Entity-centric risk; **network analytics** improve detection; graph/relationship features and customer risk rating.
- **Implication:** Use **RelationshipEdge** (and Case) in at least one detection path or report; aim for one entity-level or network-based view.

### 5.6 Model risk and documentation

- **OCC 2025:** Model risk management can be tailored to complexity; **documentation** and validation matter.
- **Implication:** **Document** scoring and rule logic; **version** rules and list usage; keep artefacts that support validation.

---

## Part 6 — Best for This Project: Step-by-Step Roadmap

A single, prioritised roadmap that fits the **current codebase** and moves it toward a **2026-grade, effectiveness-focused** AML TM engine. Each step is **actionable**, **testable**, and **aligned** with the research above.

### Phase A — Evidence and data (foundation for “effectiveness”)

| # | Step | Artefacts | Acceptance criteria |
|---|------|-----------|---------------------|
| A1 | **Data quality visibility** | Ingest: count and categorise rejections (parse_error, missing_required, invalid_value). Persist in AuditLog details (e.g. rows_rejected, rejection_reasons map). Optional: GET /ingest/quality or include in reproduce bundle. | Re-run ingest with intentional bad rows; audit log contains rows_rejected and reason codes; no silent drops without a trace. |
| A2 | **Rule performance report** | New report or API: per rule_id, count of alerts, count by disposition (open, closed, false_positive, escalate, sar). Optional: time range filter. Stored or computed from Alert + optional AuditLog. | Report shows alerts per rule and disposition breakdown; at least one test asserts structure. |
| A3 | **Disposition timeliness** | Add or use updated_at on Alert; report “average time to disposition” (or to closed) for a time window. Optional: alert created → disposition_update in AuditLog. | Metric available in report or API; test that timeliness is computed correctly for a small dataset. |

### Phase B — Governance and reproducibility

| # | Step | Artefacts | Acceptance criteria |
|---|------|-----------|---------------------|
| B1 | **Per-rule version or hash in audit** | When writing run_rules audit, include per rule_id a version or content hash (e.g. from rule module or config). Document in RULE.md. | Audit details for run_rules contain rule-level version/hash; test asserts presence. |
| B2 | **Scoring methodology document** | docs/SCORING_METHODOLOGY.md: base_risk, bands, how deltas are summed, how segment could be added later. | Doc exists and is referenced from RULE.md or RUNBOOK. |
| B3 | **Config validation** | Startup or config load: if high_risk_country list is exactly [XX, YY] (or placeholder), log WARNING or fail in strict mode. Document in RUNBOOK. | Placeholder config produces warning or failure as designed; test present. |

### Phase C — Entity/network and production readiness

| # | Step | Artefacts | Acceptance criteria |
|---|------|-----------|---------------------|
| C1 | **One rule or report using relationships** | Either (a) a simple rule that uses RelationshipEdge (e.g. “N+ distinct counterparties in window” already in network_ring) and is covered by tests, or (b) a report/API that aggregates alerts or transactions by counterparty or by edge. | At least one detection or report uses RelationshipEdge or entity-level aggregation; test coverage. |
| C2 | **Chunked run_rules** | run_rules processes transactions in chunks (e.g. by id range); each chunk commits and writes an audit entry (or one batch entry with chunk info). Optional: resume from last chunk on failure. | Large DB does not require loading all transactions in one go; test with two chunks. |
| C3 | **List versioning (sanctions / high-risk)** | Config or DB: list version or effective date for sanctions keywords and high-risk countries. Record in run_rules audit which list version was used. | Audit contains list_version or list_effective_date; doc in RULE.md. |

### Phase D — Optional but high value

| # | Step | Artefacts | Acceptance criteria |
|---|------|-----------|---------------------|
| D1 | **SAR “filed” timestamp or flag** | Optional field on Alert or Case (e.g. sar_filed_at or disposition_sar with date). Report “time to SAR” for alerts dispositioned as SAR. | If implemented, metric is available and tested. |
| D2 | **API scopes/roles** | Document current “one key = full access.” Optional: scope per key (e.g. read_only, alerts_only, full); enforce in PATCH /alerts and cases. | Doc updated; if scopes added, tests enforce. |

---

## Part 7 — Single “Next Step” Recommendation

**Best single next step:** **A1 — Data quality visibility.**

- **Why first:** It addresses “systems that actually solve”: you stop **silently losing data** and start producing **auditable evidence** of what was accepted vs rejected and why. That is the foundation for any serious “effectiveness” conversation with a supervisor or auditor.
- **Why before more features:** Without data quality visibility, every new rule and report is built on unknown data. Rule performance (A2) and timeliness (A3) are more credible once ingest is transparent.
- **Scope:** Ingest (CSV + JSONL): categorise rejections (e.g. parse_error, missing_required, invalid_value); add rows_rejected and rejection_reasons to AuditLog details; optional GET /ingest/quality or include in reproduce bundle; tests and `make ci` pass.

---

## Verification Commands (After Implementing A1)

From project root:

```bash
poetry install
make ci
```

Create a small CSV with one valid row and one invalid row (e.g. missing required field or bad date). Run ingest; query AuditLog for the ingest action and assert details_json contains rows_rejected >= 1 and a non-empty rejection reason/code.

---

## Document Control

- **Authority:** Veteran critique + FATF, EU AMLD, MAS/FCA-style guidance, Deloitte/Google/OCC/model risk and data quality sources.
- **Scope:** This AML Transaction Monitoring Engine repo; roadmap is tailored to current codebase (Poetry, Makefile, contextvars audit, schema upgrade gating, Alembic, existing Case/Alert disposition and auth).
- **Next review:** After Phase A is complete; then align Phase B/C/D with remaining gaps and regulator feedback.
