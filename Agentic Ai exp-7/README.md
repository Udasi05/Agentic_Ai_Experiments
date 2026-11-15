# Experiment 7: Automated Recruitment Workflow System

An automated, explainable recruitment workflow pipeline built using **LangGraph** and **Streamlit**.

## Features

- **Candidate Ingestion & Quarantine**: Ingests records from CSV, performs strict header and type validation, identifies duplicate candidates without deleting them, and quarantines invalid records into `rejected_records.csv` with explicit explanations.
- **Explainable Rule-Based Scoring Engine**: Calculates transparent composite scores:
  $$S = 0.40K + 0.30E + 0.30A$$
  where $K$ = Skills, $E$ = Experience, and $A$ = Assessment scores. Uses exact `Decimal` arithmetic for consistent boundary handling ($75.0$ vs $74.99$, $50.0$ vs $49.99$).
- **Workflow Routing**:
  - `SHORTLIST_REVIEW`: Score $\ge 75$
  - `MANUAL_REVIEW`: Score $\ge 50$ (or target role mismatch)
  - `NOT_SHORTLISTED_REVIEW`: Score $< 50$
- **Notification Draft Generation & Safety Guard**: Drafts status-specific notifications hiding scores and avoiding premature rejection language. Optional Gemini integration guarded by `validate_polished` which rejects score disclosures or forbidden phrasing.
- **Human-in-the-Loop Review Graph**:
  - Role-based authorization (`admin`, `hr_reviewer` authorized; `viewer` denied).
  - Actions: `APPROVE`, `EDIT` (with mandatory override reason), `HOLD`, `REQUEST_INFO`.
  - Automated dispatch with up to 2 retries on delivery failure.
- **Tamper-Evident Append-Only Audit Logging**: Compliant with data minimisation (candidate names, emails, and personal identifiers are redacted).
- **Streamlit Web Dashboard**: 4 interactive tabs (`Pipeline`, `Review`, `Audit`, `Metrics`) with visual score breakdowns, decision dispatch, and live test execution.
- **Automated Testing Suite**: 50/50 comprehensive `pytest` tests validating scoring, routing, ingestion, audit, review graphs, and security guardrails.

---

## Directory Structure

```
├── AAEEA_Experiment-7.pdf       # Original Experiment 7 specification document
├── app.py                       # Streamlit web dashboard
├── recruitment_workflow.py      # Console CLI application
├── rules.json                   # Configurable criteria weights, thresholds & version
├── requirements.txt             # Project dependencies
├── data/
│   └── candidates.csv           # 120 candidate dataset (110 valid, 10 quarantined)
├── recruitment/                 # Core modular package
│   ├── audit.py                 # Append-only audit logger with redaction
│   ├── config.py                # System-wide constants, statuses, paths
│   ├── drafts.py                # Notification drafts & LLM guardrails
│   ├── errors.py                # Custom exceptions
│   ├── ingestion.py             # CSV reader, validator, normalizer & deduplication
│   ├── metrics.py               # KPI and evaluation computations
│   ├── notifications.py         # Simulated dispatcher with retry logic
│   ├── pipeline_graph.py        # LangGraph StateGraph for pipeline
│   ├── review_graph.py          # LangGraph StateGraph for review decisions
│   ├── routing.py               # Rule-based routing logic
│   ├── rules.py                 # Rules schema validation
│   ├── scoring.py               # Decimal scoring engine & explainability
│   └── simulation.py            # Automated review benchmark simulation
├── scripts/
│   └── generate_data.py         # Deterministic data generation script
├── tests/                       # 50 unit & integration test cases
└── docs/
    ├── API.md                   # Full public API reference
    └── SPEC.md                  # Detailed system specification
```

---

## Installation & Setup

1. **Clone or Navigate to the Directory**:
   ```bash
   cd "d:\Projects\Agentic Ai exp-7"
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

---

## Running the Application

### 1. Console Workflow (CLI)
Run the pipeline directly from the command line:
```bash
python recruitment_workflow.py
```

To run with the complete simulated human review and print the full observation metrics table:
```bash
python recruitment_workflow.py --simulate-review
```

### 2. Streamlit Web Dashboard
Launch the interactive web UI:
```bash
streamlit run app.py
```
Open your browser at `http://localhost:8501`.

- **Pipeline Tab**: View all candidate scores, queues, and quarantined records.
- **Review Tab**: Examine score breakdown bars, review/edit drafts, and submit decisions (`APPROVE`, `EDIT`, `HOLD`, `REQUEST_INFO`). Toggle roles in the sidebar to test role permissions.
- **Audit Tab**: Inspect and filter append-only audit events and download `audit_log.csv`.
- **Metrics Tab**: Inspect KPI metric cards and click **Run tests** to trigger all 50 tests live.

### 3. Running Test Suite
Execute the 50 automated tests with pytest:
```bash
pytest tests
```
All 50 tests will pass.

