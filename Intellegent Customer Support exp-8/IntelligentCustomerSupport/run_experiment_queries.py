"""Run the report's guided examples against local Qwen and MCP tool handlers."""
import json
from pathlib import Path
from classifier import classify_rules
from resolver import load_kb, retrieve, route
from ollama_client import classify_with_ollama, grounded_draft
from mcp_client import run_mcp_workflow

ROOT=Path(__file__).parent
CONFIG=json.loads((ROOT/"config.json").read_text(encoding="utf-8"))
QUERIES=[
 {"query_id":"EXP01","query_text":"I cannot log in to my account after resetting my password."},
 {"query_id":"EXP02","query_text":"My payment was deducted but the invoice is missing. Please help urgently."},
 {"query_id":"EXP03","query_text":"The application is down for all users in our company."},
 {"query_id":"EXP04","query_text":"Please add dark mode to the dashboard."},
 {"query_id":"EXP05","query_text":"It is not working."},
 {"query_id":"EXP06","query_text":"Can CloudCRM connect to a fictional quantum flux capacitor?"},
]
results=[]
for query in QUERIES:
    q=query["query_text"]
    mcp=run_mcp_workflow(q)
    rule=classify_rules(q)
    model_error=""
    try: model,seconds=classify_with_ollama(q,CONFIG["ollama_url"],CONFIG["model"])
    except Exception as error:
        model=rule; seconds=0; model_error=str(error)
    # Preserve the risk-first deterministic safeguard exactly as the app does.
    final=rule if rule["priority"]=="P1" or rule["intent"]=="Security Concern" else model
    article,score,matched=retrieve(q,load_kb(),final["intent"])
    route_name=route(final,score,article)
    draft_error=""
    if article:
        try: draft=grounded_draft(q,article,CONFIG["ollama_url"],CONFIG["model"])
        except Exception as error: draft=article["response"]; draft_error=str(error)
    else: draft="No approved article; no answer generated."
    results.append({**query,"mcp_classification":mcp["classification"],"qwen_classification":model,"qwen_error":model_error,"final_classification":final,"article_id":article["article_id"] if article else None,"match_score":score,"matched_keywords":matched,"route":route_name,"response_draft":draft,"draft_error":draft_error,"qwen_classification_seconds":round(seconds,2)})
path=ROOT/"experiment_query_results.json"
path.write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding="utf-8")
print(json.dumps(results,indent=2,ensure_ascii=False))
print(f"\nSaved {len(results)} query runs to {path}")
