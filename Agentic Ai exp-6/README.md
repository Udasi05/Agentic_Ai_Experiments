# PR Review Assistant — Experiment 6

A comprehensive PR Review Assistant built using the **Model Context Protocol (MCP)** that connects to multiple MCP servers, discovers tools dynamically, enforces safety policies, and produces automated code review verdicts through an interactive Streamlit application.

---

## Aim
Design and implement a PR Review Assistant using the Model Context Protocol (MCP) that:
- Connects one MCP client to a custom review server and to the external filesystem and git MCP servers
- Discovers tools dynamically and plans a review with a Gemini-based planner agent
- Validates plans with a supervisor agent and blocks HIGH-risk tools through a policy layer
- Runs independent tasks in parallel and dependent tasks in phases, with validation, retry and tracing
- Produces a **READY** or **NEEDS WORK** verdict through a Streamlit application

---

## System Architecture

```
Streamlit App
      │
      ▼
Planner Agent (Gemini + Rule-based Fallback)
      │
      ▼
Supervisor Agent (Tool & Argument Validation)
      │
      ▼
Safety / Policy Layer (LOW / MEDIUM / HIGH Risk Blocking)
      │
      ▼
MCP Client (one ClientSession per server | dependency-aware phases | asyncio.gather)
      │
      ├───────────────────────┬───────────────────────┐ (over stdio)
      ▼                       ▼                       ▼
PR Review Server        Filesystem MCP           Git MCP
(Custom FastMCP)        (External npm)          (External pip)
  - analyze_python        - list_directory        - git_status
  - scan_secrets          - read_text_file        - git_diff_unstaged
  - search_code           - directory_tree        - git_commit
  - run_tests             - write_file (HIGH)     - git_add (HIGH)
      │                       │                       │
      └───────────────────────┼───────────────────────┘
                              ▼
                  Project Folder + Git Repository
                              │
      ┌───────────────────────┼───────────────────────┬───────────────────────┐
      ▼                       ▼                       ▼                       ▼
  Validator            Retry & Recovery          Trace (JSONL)         Verdict & Report
```

---

## MCP Servers and Tool Registry

| Server | Type | Tools Discovered | Key Capabilities |
|---|---|:---:|---|
| **PR Review Server** | Custom (FastMCP) | 4 | `analyze_python`, `scan_secrets`, `search_code`, `run_tests` |
| **Filesystem MCP** | External (npm) | 14 | `read_file`, `read_text_file`, `list_directory`, `write_file`, `directory_tree` |
| **Git MCP** | External (pip) | 12 | `git_status`, `git_diff_unstaged`, `git_commit`, `git_add`, `git_log` |
| **Total** | | **30** | All unified into a single client registry |

---

## Four-Layer Execution Control

1. **Planner Agent**:
   - Primary: Uses Google Gemini API (`gemini-2.0-flash`) to generate a task dependency graph.
   - Fallback: Deterministic rule-based planner that constructs standard 3-phase DAG plans.
2. **Supervisor Agent**:
   - Rejects unknown tools not in the registry.
   - Rejects missing required parameters.
   - Verifies all dependencies reference valid preceding task IDs without cyclic graphs.
3. **Policy Layer**:
   - Classifies tools into `LOW`, `MEDIUM`, or `HIGH` risk.
   - Blocks `HIGH`-risk mutation tools (e.g., `git_commit`, `git_add`, `write_file`, `edit_file`, `delete_file`) before they reach the server.
4. **Validator & Retry Engine**:
   - Checks result structures and categorizes failures (`security`, `input`, `tool`, `timeout`, `execution`).
   - Retries only `timeout` and `execution` errors up to 3 times with exponential backoff.

---

## Streamlit Application Tabs

1. **Review**:
   - Dark header card showing verdict (`NEEDS WORK` / `READY`) and unique `TRACE: <ID>`.
   - Plain-English review narrative.
   - Metric cards: **Files**, **Issues** (High / Med / Low), **Tests** (Passed / Failed), and **Execution Time**.
   - Severity-sorted issue breakdown table (`SEVERITY`, `FILE`, `LINE`, `RULE`, `MESSAGE`).
2. **Plan**:
   - Multi-phase execution table with status (`OK`, `BLOCKED`, `REJECTED`, `SKIPPED`), timing in ms, and policy notes.
3. **Trace**:
   - Live JSONL trace inspectable in table format (`TASK`, `SERVER`, `TOOL`, `TRY`, `STATUS`, `MS`, `TIME`, `ERROR`).
4. **Benchmark**:
   - Interactive sequential vs. parallel performance comparison across 5 runs.
   - 30.4% speedup on independent read-only tasks.
5. **Tools**:
   - Full 30-tool catalogue with server sources, risk classifications, and descriptions.

---

## Setup & Execution

### 1. Requirements

Install required dependencies:

```bash
pip install -r requirements.txt
```

### 2. (Optional) Configure Gemini API

Copy the `.env.example` file to `.env`:

```bash
cp .env.example .env
```

And set your API key:

```env
GEMINI_API_KEY=your_gemini_api_key_here
```

*(Note: If no API key is provided, the system automatically uses the built-in rule-based planner).*

### 3. Run the Streamlit Application

```bash
# Using run.py
python run.py

# Or directly with streamlit
streamlit run app/streamlit_app.py
```

### 4. Run the Test Suite

```bash
python -m pytest tests/ -v
```

All 28 system and benchmark tests validate:
- Tool risk classification and policy blocking
- Error classification (`[security]`, `[input]`, `[timeout]`, `[execution]`)
- Supervisor plan approval and rejection
- DAG dependency ordering
- Live and baseline performance benchmarks

---

## Project Structure

```
├── requirements.txt            # Project dependencies (mcp, streamlit, pytest, etc.)
├── .env.example                # Template for Gemini API key
├── run.py                      # One-click launcher for the Streamlit app
├── README.md                   # Complete documentation
├── src/
│   ├── __init__.py
│   ├── config.py               # Paths, model parameters, timeout configs
│   ├── mcp_server.py           # Custom FastMCP server (4 review tools)
│   ├── mcp_client.py           # Multi-server client & 30-tool registry
│   ├── planner.py              # Gemini-based & rule-based planner agents
│   ├── supervisor.py           # Supervisor agent validating DAG plans
│   ├── policy.py               # Tool risk classification & blocking layer
│   ├── executor.py             # Dependency-aware parallel execution engine
│   ├── validator.py            # Result validator & error classifier
│   ├── retry.py                # Retry mechanism with backoff
│   ├── tracer.py               # JSONL structured trace logger
│   └── benchmark.py            # Sequential vs. parallel benchmark runner
├── app/
│   ├── __init__.py
│   └── streamlit_app.py        # Complete Streamlit UI
├── sample_project/             # Review target repository with intentional defects
│   ├── calculator.py           # Has bare except (line 38) & missing docstrings (lines 25, 31, 35)
│   ├── config.py               # Has hardcoded credentials (lines 3, 4)
│   ├── utils.py                # Clean helper module
│   └── tests/
│       ├── __init__.py
│       └── test_calculator.py  # Has failing test (test_percent, fails with assert 2.5 == 25)
├── logs/
│   └── mcp_traces.jsonl        # Output trace logs
└── tests/
    ├── __init__.py
    ├── test_system.py          # 26 unit tests covering all 4 layers & failure matrix
    └── test_benchmark.py       # Benchmark validation tests
```

---

*Experiment 6 — PR Review Assistant using MCP*
