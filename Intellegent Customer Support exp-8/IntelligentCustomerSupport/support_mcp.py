"""Local MCP server: exposes deterministic support tools over stdio."""
from mcp.server.fastmcp import FastMCP
from classifier import classify_rules
from resolver import load_kb, retrieve, route

mcp=FastMCP("Intelligent Customer Support")

@mcp.tool()
def classify_support_query(query: str) -> dict:
    """Classify a SaaS support query into intent, complexity, priority, and reason."""
    return classify_rules(query)

@mcp.tool()
def search_approved_knowledge(query: str, intent: str = "") -> dict:
    """Retrieve the best approved knowledge article and keyword match score."""
    article,score,matched=retrieve(query,load_kb(),intent or None)
    return {"article":article,"score":score,"matched_keywords":matched}

@mcp.tool()
def decide_support_route(intent: str, complexity: str, priority: str, score: int, article_found: bool) -> dict:
    """Apply risk-first support routing rules."""
    return {"route":route({"intent":intent,"complexity":complexity,"priority":priority},score,article_found)}

if __name__ == "__main__": mcp.run()
