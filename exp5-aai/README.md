# Experiment 5 — Multi-Agent E-Commerce Product Analysis & Recommendation Pipeline

## Run

```powershell
pip install -r requirements.txt
streamlit run app.py          # UI at http://localhost:8501
python run_cli.py --auto-approve   # console run + observation table
python -m pytest -q           # 19 tests (functional, failure, security, performance, UI)
```

## Workflow

```
Query → Planner → Validator(CP1) → Router ─┬─ Search Agent A ─┐
                                           ├─ Search Agent B ─┼→ Supervisor: synchronize + resolve conflicts
                                           └─ Search Agent C ─┘
      → Filter → Validator(CP2) → Comparison → Ranking → Validator(final) → Supervisor → Human approval → Final
```

## Layout

| File | Purpose |
|---|---|
| `ecommerce_agents/data.py` | 3 catalog sources (A official, B marketplace, C aggregator) with deliberate conflicts, gaps and an out-of-stock item |
| `ecommerce_agents/state.py` | Shared workflow state: role-based writes, write-once fields, SHA-256 integrity hash, trace/messages/metrics |
| `ecommerce_agents/tools.py` | MCP-style registry: registration, discovery, per-agent authorization, schema validation, timeouts, caching, fault injection |
| `ecommerce_agents/logic.py` | Query parsing + injection screening, synchronization, filtering, comparison, scoring, validation |
| `ecommerce_agents/agents.py` | Planner, Router, Search A/B/C, Filter, Comparison, Ranking, Validator, Supervisor |
| `ecommerce_agents/orchestrator.py` | Dependency-aware sequential/parallel execution, bounded retry, tracing, cost metrics, human-in-the-loop |
| `ecommerce_agents/evaluation.py` | Functional / failure / security / performance suites and the observation table |
| `app.py` | Streamlit UI |

## Ranking

`score = 100 × Σ wᵢ · nᵢ` where `nᵢ` is the min-max normalized factor across qualifying products (price inverted).
Base weights are price 0.30, rating 0.30, RAM 0.20, storage 0.20. Any factor the customer specified is multiplied by 1.5 and then all weights are renormalized.
The Validator recomputes every score and re-derives the order independently.

## Cost units

1 per agent execution, 2 per tool call, 3 per retry, 0.01 per product record processed. These are relative units, not money.

The MCP-style layer is a simplified in-process interface. It does not implement the full MCP protocol, which is covered in Experiment 06.
