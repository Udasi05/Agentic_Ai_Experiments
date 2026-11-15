"""In-process bridge to tool handlers registered on the local FastMCP server."""
from support_mcp import classify_support_query, search_approved_knowledge, decide_support_route

def run_mcp_workflow(query):
    classification=classify_support_query(query)
    retrieval=search_approved_knowledge(query,classification["intent"])
    routing=decide_support_route(classification["intent"],classification["complexity"],classification["priority"],retrieval["score"],bool(retrieval["article"]))
    return {"classification":classification,"retrieval":retrieval,"route":routing["route"]}
