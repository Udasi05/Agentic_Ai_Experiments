# Intelligent Customer Support System

A classroom SaaS support workflow built with Streamlit, local Ollama Qwen 2.5 7B, approved knowledge retrieval, SQLite tickets, and a local Model Context Protocol (MCP) server.

## Run it

1. Install Python 3.10+ and [Ollama](https://ollama.com/download).
2. In a terminal, pull the requested local model: `ollama pull qwen2.5:7b`.
3. From this folder, create a virtual environment and install dependencies:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```
4. Start Ollama (usually `ollama serve`) and launch the app:
   ```powershell
   streamlit run app.py
   ```
5. Open **System setup** to check the local endpoint/model. Use **Guided support** for the visible step-by-step workflow or **Batch tests** for test scenarios and the full dataset.

## MCP integration

`support_mcp.py` registers three local FastMCP tools: `classify_support_query`, `search_approved_knowledge`, and `decide_support_route`. The Streamlit app calls these registered handlers locally and displays each tool stage. The same module can be launched as a stdio MCP server for another MCP host. The app's local handler mode avoids a Windows subprocess transport dependency. No customer query is sent to a remote model provider; Qwen inference uses the local Ollama endpoint.

To inspect the MCP server independently, install the dependencies and run `python support_mcp.py`; it speaks MCP over stdio and is intended to be launched by an MCP host.

## Project map

- `app.py`: Streamlit UI, workflow trace, batch tests, ticket table, metrics.
- `support_mcp.py`, `mcp_client.py`: local MCP server and app client.
- `classifier.py`, `resolver.py`, `ollama_client.py`: rule baseline, approved retrieval, local model calls.
- `customer_queries.csv`: 500 synthetic rows; includes empty text, duplicate ID, ambiguous query, high-priority billing, and no-KB query.
- `generate_dataset.py`: deterministic dataset generator.
- `test_cases.json`: 14 executable lab scenarios, including four malicious-input cases.
- `knowledge_base.json`: approved sample support articles only.
- `config.json`: endpoint, model, match thresholds, and sample SLA targets.
- `tickets.db`: created locally when a ticket is issued.

## Important lab behavior

The match score is a keyword heuristic, not a calibrated confidence probability. Security incidents and widespread outages take precedence over model output and always escalate. Qwen classifications are schema-checked; when Ollama is down or returns invalid output, the rule baseline is used. Response drafts are grounded only in the selected approved article. A draft is never represented as a completed resolution. Notifications are shown as drafts/simulations; no real email is sent. Synthetic IDs and queries are used throughout.

The **14 scenario tests** run deterministic validation, classification and routing checks, including prompt-injection, data-exfiltration and credential-abuse examples. Security cases route to urgent human review, and the guided workflow skips Qwen response drafting for Security Concern queries. Notification delivery and full ticket lifecycle operations are not implemented in this lab build.

## Evaluation

The dashboard reports dataset processing, validation rejects, KB article coverage, and escalation/review share. KB coverage is not a resolution rate: count a resolution only after its documented completion criterion is met. Classification accuracy requires comparing predictions with the `ground_truth_intent` labels and defining excluded invalid rows. SLA values are illustrative lab targets, not contractual commitments.
