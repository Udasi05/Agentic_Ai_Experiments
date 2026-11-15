"""
Planner Agent — converts a review request into a task graph.
Primary: Gemini API. Fallback: Rule-based planner.
"""

import json
import re
from typing import List, Dict, Any, Optional

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

from src.config import GEMINI_API_KEY, GEMINI_MODEL


def _build_prompt(request: str, tool_catalog: list) -> str:
    """Build the prompt for Gemini to generate a task plan."""
    simplified_catalog = [
        {"name": t["name"], "server": t.get("server", ""), "description": t.get("description", "")}
        for t in tool_catalog
    ]
    catalog_text = json.dumps(simplified_catalog, indent=2)

    return f"""You are a PR review planner agent for Experiment 6 (Model Context Protocol).
Given a user's review request and an MCP tool catalogue, convert the request into a DAG task graph.

Return JSON in the exact format:
{{
  "tasks": [
    {{"id": "TASK-001", "tool": "git_status", "args": {{}}, "depends_on": []}},
    {{"id": "TASK-002", "tool": "analyze_python", "args": {{"file": "calculator.py"}}, "depends_on": ["TASK-001"]}},
    {{"id": "TASK-003", "tool": "scan_secrets", "args": {{}}, "depends_on": ["TASK-001"]}},
    {{"id": "TASK-004", "tool": "run_tests", "args": {{"test_path": "tests/"}}, "depends_on": ["TASK-002", "TASK-003"]}}
  ]
}}

Execution Rules:
1. Phase 1 tasks (like git_status) have no dependencies.
2. Phase 2 tasks (like analyze_python, scan_secrets, git_diff_unstaged) run in parallel and depend on Phase 1.
3. Phase 3 tasks (like run_tests) run after Phase 2 tasks succeed.
4. If the user explicitly asks to stage, add, or commit changes, include "git_add" and "git_commit" as subsequent tasks in the plan.
5. Use only tools available in the catalogue.
6. Return ONLY valid JSON.

Tool Catalogue:
{catalog_text}

User Request: {request}
"""


def ask_gemini(prompt: str) -> Optional[str]:
    """Ask Gemini to generate a plan. Returns None if unavailable."""
    if not GENAI_AVAILABLE or not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        return None

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"  ⚠ Gemini planner failed: {e}")
        return None


def rule_based_plan(request: str, tool_catalog: list) -> List[Dict[str, Any]]:
    """
    Fallback rule-based planner.
    Produces plans matching Fig. 3 or Fig. 4 based on request keywords.
    """
    req_lower = request.lower()
    include_commit = any(k in req_lower for k in ("commit", "stage", "git_add", "git_commit", "push"))

    if include_commit:
        # Plan matching Fig. 4 in Experiment 6
        return [
            {"id": "TASK-001", "tool": "git_status", "server": "git", "args": {}, "depends_on": []},
            {"id": "TASK-002", "tool": "git_diff_unstaged", "server": "git", "args": {}, "depends_on": ["TASK-001"]},
            {"id": "TASK-003", "tool": "analyze_python", "server": "review", "args": {"file": "calculator.py"}, "depends_on": ["TASK-001"]},
            {"id": "TASK-004", "tool": "scan_secrets", "server": "review", "args": {}, "depends_on": ["TASK-001"]},
            {"id": "TASK-005", "tool": "run_tests", "server": "review", "args": {"test_path": "tests/"}, "depends_on": ["TASK-003", "TASK-004"]},
            {"id": "TASK-006", "tool": "git_add", "server": "git", "args": {"files": ["."]}, "depends_on": ["TASK-005"]},
            {"id": "TASK-007", "tool": "git_commit", "server": "git", "args": {"message": "fix"}, "depends_on": ["TASK-006"]},
        ]
    else:
        # Standard Plan matching Fig. 3 in Experiment 6
        return [
            {"id": "TASK-001", "tool": "git_status", "server": "git", "args": {}, "depends_on": []},
            {"id": "TASK-002", "tool": "analyze_python", "server": "review", "args": {"file": "calculator.py"}, "depends_on": ["TASK-001"]},
            {"id": "TASK-003", "tool": "scan_secrets", "server": "review", "args": {}, "depends_on": ["TASK-001"]},
            {"id": "TASK-004", "tool": "run_tests", "server": "review", "args": {"test_path": "tests/"}, "depends_on": ["TASK-002", "TASK-003"]},
        ]


def create_plan(request: str, tool_catalog: list) -> tuple:
    """
    Create a review plan from a request.
    Returns (tasks, planner_type) where planner_type is 'Gemini' or 'Rules'.
    """
    prompt = _build_prompt(request, tool_catalog)
    raw = ask_gemini(prompt)

    if raw:
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```[a-zA-Z]*\n", "", cleaned)
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
            cleaned = cleaned.strip()

            data = json.loads(cleaned)
            tasks = data.get("tasks", data) if isinstance(data, dict) else data
            if isinstance(tasks, list) and len(tasks) > 0:
                return tasks, "Gemini"
        except (json.JSONDecodeError, KeyError, Exception):
            pass

    # Fallback to rule-based planner
    tasks = rule_based_plan(request, tool_catalog)
    return tasks, "Rules"
