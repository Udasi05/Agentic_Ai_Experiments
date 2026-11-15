# LABORATORY REPORT: EXPERIMENT 6

**Course:** Agentic AI Laboratory  
**Experiment Title:** Design and Implementation of a PR Review Assistant using the Model Context Protocol (MCP)  
**Student Name:** Pankaj Gupta  
**Roll No / Batch:** D17A / 21  

---

## 1. Aim
To design, implement, and evaluate an automated Pull Request (PR) Review Assistant using the **Model Context Protocol (MCP)** that:
1. Connects a single unified MCP client over `stdio` to a custom PR review server, an external filesystem server, and a git MCP server.
2. Dynamically discovers tools and plans an automated review workflow with a Gemini-based planner agent (with rule-based fallback).
3. Validates execution plans with a supervisor agent and enforces safety policies to block `HIGH`-risk mutation tools.
4. Executes independent review tasks concurrently in dependency-aware phases using `asyncio.gather`.
5. Classifies errors, applies exponential backoff retries for transient failures, logs structured JSONL execution traces, and renders an interactive verdict (`READY` or `NEEDS WORK`) via a Streamlit dashboard.

---

## 2. Theoretical Background

### 2.1 Model Context Protocol (MCP)
The **Model Context Protocol (MCP)** is an open protocol developed to standardize how AI applications and agents access external tools, prompts, and resources. Instead of hardcoding API integrations for each external system, MCP provides a client-server architecture:
- **Server:** Exposes capabilities (tools, prompts, resources) described with standard JSON Schemas.
- **Client:** Discovers available tools via `tools/list` and invokes them via `tools/call`.
- **Transport:** In this experiment, the communication transport is `stdio` (standard input/output pipes), where each MCP server runs as a managed child process of the client application.

### 2.2 Multi-Server Tool Discovery
In modern software engineering workflows, tools originate from multiple domains:
- **Git version control** (`git_status`, `git_diff_unstaged`, `git_commit`)
- **Filesystem operations** (`read_file`, `list_directory`, `write_file`)
- **Code intelligence & testing** (`analyze_python`, `scan_secrets`, `run_tests`)

A unified MCP client opens one `ClientSession` per server and aggregates all 30 discovered tools into a single catalog, abstracting away server ownership from the planning and execution agents.

### 2.3 Four-Layer Agentic Control Flow
To prevent untrusted or hallucinated LLM execution, a layered defense-in-depth architecture is implemented:
1. **Planner Layer (Gemini / Rules):** Decomposes the user request into a Directed Acyclic Graph (DAG) of tasks with explicit dependencies.
2. **Supervisor Layer:** Enforces syntactic validity: ensures tools exist in the discovered registry, parameters match expected schemas, and task dependency IDs are valid and non-cyclical.
3. **Policy Layer:** Classifies all operations into `LOW`, `MEDIUM`, or `HIGH` risk. Blocks destructive mutations (`git_commit`, `git_add`, `write_file`, `delete_file`) before they can reach the server.
4. **Executor & Validator Layer:** Executes tasks in topological phases. Results are validated against schema expectations, and errors are categorized for selective retry.

---

## 3. System Architecture

```
                       User Request / PR Event
                                  │
                                  ▼
               ┌─────────────────────────────────────┐
               │    Planner Agent (Gemini / Rules)   │
               └──────────────────┬──────────────────┘
                                  │ (Task DAG)
                                  ▼
               ┌─────────────────────────────────────┐
               │    Supervisor Agent (Validation)    │
               └──────────────────┬──────────────────┘
                                  │ (Approved Tasks)
                                  ▼
               ┌─────────────────────────────────────┐
               │     Safety Policy (Risk Filter)     │
               │  [LOW / MEDIUM Allowed | HIGH Block]│
               └──────────────────┬──────────────────┘
                                  │
                                  ▼
                 ┌─────────────────────────────────┐
                 │        Unified MCP Client       │
                 │   (Phased asyncio.gather DOP=2) │
                 └────────────────┬────────────────┘
                                  │ stdio
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
┌───────────────┐         ┌───────────────┐         ┌───────────────┐
│PR Review Server│         │Filesystem MCP │         │    Git MCP    │
│(Custom FastMCP│         │(Official npm) │         │(Official pip) │
│   4 tools)    │         │  14 tools)    │         │  12 tools)    │
└───────┬───────┘         └───────┬───────┘         └───────┬───────┘
        │                         │                         │
        └─────────────────────────┼─────────────────────────┘
                                  ▼
                       Project & Git Workspace
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
┌───────────────┐         ┌───────────────┐         ┌───────────────┐
│   Validator   │         │Retry & Backoff│         │JSONL Tracer   │
│(Result verify)│         │(Timeout/Exec) │         │(logs/traces)  │
└───────────────┘         └───────────────┘         └───────┬───────┘
                                                            ▼
                                                ┌───────────────────────┐
                                                │ Streamlit UI & Verdict│
                                                │ (READY / NEEDS WORK)  │
                                                └───────────────────────┘
```

---

## 4. Discovered Tool Registry (30 Tools)

| Server | Type | Discovered Tools | Risk Classification |
|---|---|:---:|---|
| **PR Review Server** | Custom (FastMCP) | 4 | `analyze_python` (LOW), `scan_secrets` (LOW), `search_code` (LOW), `run_tests` (MEDIUM) |
| **Filesystem MCP** | External (npm) | 14 | `read_file` (LOW), `read_text_file` (LOW), `read_media_file` (LOW), `read_multiple_files` (LOW), `list_directory` (LOW), `list_directory_with_sizes` (LOW), `directory_tree` (LOW), `get_file_info` (LOW), `search_files` (LOW), `list_allowed_directories` (LOW), `write_file` (HIGH), `edit_file` (HIGH), `create_directory` (HIGH), `move_file` (HIGH) |
| **Git MCP** | External (pip) | 12 | `git_status` (LOW), `git_diff_unstaged` (LOW), `git_diff_staged` (LOW), `git_diff` (LOW), `git_log` (LOW), `git_show` (LOW), `git_list_branches` (LOW), `git_create_branch` (MEDIUM), `git_commit` (HIGH), `git_add` (HIGH), `git_reset` (HIGH), `git_checkout` (HIGH) |
| **Total** | | **30** | **20 LOW | 2 MEDIUM | 8 HIGH** |

---

## 5. Implementation Details

### 5.1 Custom FastMCP Review Server (`src/mcp_server.py`)
- Employs a path containment sandbox (`safe_path`) preventing directory traversal outside `sample_project`.
- **AST Code Analysis (`analyze_python`):** Parses the abstract syntax tree to detect:
  - Bare `except:` clauses without explicit exception classes.
  - Functions lacking PEP 257 docstrings.
  - Overly complex functions exceeding 50 lines.
- **Credential Scanning (`scan_secrets`):** Scans source files with regex heuristics for unmasked API tokens, database passwords, and private keys.
- **Pytest Integration (`run_tests`):** Executes unit tests inside the repository with a 30-second timeout, extracting pass/fail metrics and assertion diffs.

### 5.2 Dependency-Aware Parallel Execution (`src/executor.py`)
Tasks are grouped into topological layers based on dependency depth:
- **Phase 1 (Depth 0):** `git_status` runs to discover modified files.
- **Phase 2 (Depth 1):** `analyze_python` and `scan_secrets` execute concurrently using `asyncio.gather` (Degree of Parallelism = 2).
- **Phase 3 (Depth 2):** `run_tests` executes sequentially after validation of static analysis results.

### 5.3 Error Classification & Failure Matrix
Errors are inspected and categorized to prevent infinite loops on unrecoverable errors:

| Task ID | Tool | Error Reason | Classification | Action Taken |
|---|---|---|---|---|
| `TASK-001` | `read_text_file` | Path outside project: `../etc/passwd` | **Security** | Terminate attempt; no retry |
| `TASK-002` | `analyze_python` | File not found: `missing.py` | **Input** | Terminate attempt; no retry |
| `TASK-003` | `run_tests` | Tests timed out after 30 seconds | **Timeout** | Retried up to 3 times with exponential backoff |
| `TASK-004` | `delete_everything` | Unknown tool | **Supervisor** | Rejected before dispatch (0 attempts) |
| `TASK-005` | `scan_secrets` | Dependency `TASK-001` failed | **Dependency** | Skipped automatically |

---

## 6. Experimental Results & Observations

### 6.1 Review Results on Sample Project
The sample codebase containing intentional defects was evaluated by the assistant:

```
========================================
VERDICT: NEEDS WORK
TRACE ID: C6D354AD
========================================
Summary: Your pull request needs work because it currently exposes potential secrets in the configuration file and contains a failing test in the calculator tests. Additionally, you need to fix a bare except clause, add missing docstrings to several functions, and address a few minor style issues. Tests: 5 passed, 1 failed.
Files Reviewed: 4
Issues Found: 7 (3 High, 1 Medium, 3 Low)
```

#### Detailed Issues Breakdown:
| Severity | File | Line | Rule | Message |
|---|---|:---:|---|---|
| 🔴 **HIGH** | `config.py` | 3 | `Hardcoded-credential` | Possible secret: `API_KE***` |
| 🔴 **HIGH** | `config.py` | 4 | `Hardcoded-credential` | Possible secret: `DB_PAS***` |
| 🔴 **HIGH** | `test_calculator.py` | - | `test failure` | `assert 2.5 == 25` |
| 🟡 **MEDIUM** | `calculator.py` | 38 | `bare-except` | Bare except clause |
| 🟢 **LOW** | `calculator.py` | 25 | `missing-docstring` | `calculate_square` has no docstring |
| 🟢 **LOW** | `calculator.py` | 31 | `missing-docstring` | `percent` has no docstring |
| 🟢 **LOW** | `calculator.py` | 35 | `missing-docstring` | `safe_divide` has no docstring |

### 6.2 Policy Layer Enforcement Verification
When tested with an untrusted request:  
`"Review the project, then stage and commit all changes with message fix"`

The Policy Layer successfully intercepted and blocked destructive actions:
- `git_status`: **ALLOWED** (LOW)
- `git_diff_unstaged`: **ALLOWED** (LOW)
- `analyze_python`: **ALLOWED** (LOW)
- `scan_secrets`: **ALLOWED** (LOW)
- `run_tests`: **ALLOWED** (MEDIUM)
- `git_add`: **BLOCKED** (`HIGH-risk tools are not permitted`)
- `git_commit`: **BLOCKED** (`HIGH-risk tools are not permitted`)

### 6.3 Performance Evaluation: Sequential vs. Parallel Execution
Benchmarks were conducted across 5 independent runs comparing sequential execution with phased parallel execution (`asyncio.gather`):

#### Scenario A: Read-Only Tasks (6 Tasks)
| Run | Sequential (ms) | Parallel (ms) | Speedup / Reduction |
|:---:|:---:|:---:|:---:|
| 1 | 36.29 | 21.30 | 41.31 % |
| 2 | 27.83 | 22.41 | 19.48 % |
| 3 | 32.05 | 25.99 | 18.91 % |
| 4 | 24.63 | 18.76 | 23.83 % |
| 5 | 27.58 | 14.77 | 46.45 % |
| **Average** | **29.68 ms** | **20.65 ms** | **30.43 % Time Reduction** |

#### Scenario B: Tasks Including Pytest Test Run (7 Tasks)
| Scenario | Tasks | Sequential (ms) | Parallel (ms) | Time Reduction |
|---|:---:|:---:|:---:|:---:|
| **Read-only tasks** | 6 | 29.68 | 20.65 | **30.43 %** |
| **With run_tests** | 7 | 332.44 | 326.49 | **1.79 %** |

**Analytical Deduction:** Parallel execution yielded a substantial **30.43% latency reduction** on I/O and AST-bound read-only tasks. However, when the heavy `pytest` subprocess execution (~300 ms) was included, the overall parallel gain dropped to **1.79%** due to Amdahl's Law, as the total duration was dominated by the sequential test execution bottleneck.

---

## 7. Viva Voce Questions & Answers

**Q1: What is the Model Context Protocol (MCP) and why is it preferred over custom REST APIs for AI Agents?**  
*Answer:* MCP establishes an open, standard protocol for AI agents to discover and invoke tools, inspect resources, and retrieve prompts. Unlike ad-hoc REST endpoints, MCP defines standardized JSON Schema parameter definitions, standard error structures, and transport abstraction (stdio, SSE), allowing one client to interoperate with arbitrary heterogeneous tool servers without custom glue code.

**Q2: Why was stdio transport chosen instead of HTTP/SSE in this experiment?**  
*Answer:* The `stdio` transport allows the MCP client to launch server processes directly as child processes using standard pipes. This ensures zero network port binding, process-level sandboxing, immediate lifecycle termination upon client exit, and low latency inter-process communication without opening firewall ports.

**Q3: How does the Supervisor Agent prevent circular dependencies?**  
*Answer:* The supervisor constructs a directed adjacency list from the planned task DAG and performs a Depth-First Search (DFS) topological cycle check. If a task ID appears in its own ancestor traversal stack (`in_stack`), a cycle is detected and the plan is rejected prior to execution.

**Q4: Why are HIGH-risk tools blocked at the Policy layer rather than the Server layer?**  
*Answer:* Enforcing policy in the client's pre-execution pipeline (defense-in-depth) ensures that unsafe mutation tools (`git_commit`, `write_file`) are neutralized before any subprocess invocation or session dispatch occurs. This provides complete auditability and prevents accidental workspace modification even if an external server lacks access controls.

**Q5: Why are only timeout and execution errors retried, while security and input errors are not?**  
*Answer:* Security errors (e.g. permission denied, path traversal) and input errors (e.g. file not found) are deterministic: retrying them with identical parameters will inevitably fail and waste computational budget. Conversely, timeouts and execution crashes are often transient (e.g., resource contention, temporary lock) and can succeed upon retry with exponential backoff.

---

## 8. Conclusion
The PR Review Assistant successfully demonstrates the integration of the **Model Context Protocol (MCP)** in an automated software quality assurance workflow. By aggregating three distinct MCP servers into a single 30-tool registry, the system demonstrated multi-server tool discovery, robust LLM-driven DAG planning, defense-in-depth policy enforcement, selective failure retries, and comprehensive performance benchmarking. Phased parallel execution yielded a **30.43% time reduction** for read-only analytical workloads, proving the efficiency of agentic workflows in automated code review.

---
*Report generated and validated for Experiment 6 submission.*

