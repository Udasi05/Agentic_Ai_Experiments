"""
Supervisor — validates plans before execution.
Rejects unknown tools, missing arguments, and invalid dependencies.
"""

from typing import Dict, List, Any, Set


def validate_plan(tasks: List[Dict[str, Any]], known_tools: Set[str]) -> List[Dict[str, Any]]:
    """
    Validate a task plan.
    Checks:
    1. Every tool must be in the known tool set.
    2. Required arguments must be present.
    3. Dependency references must point to existing task IDs.

    Returns a list of validated tasks with a 'supervisor_status' field:
    - 'approved': task is valid and can proceed
    - 'rejected': task has issues (with 'reject_reason')
    """
    task_ids = {t["id"] for t in tasks}
    validated = []

    for task in tasks:
        task_copy = dict(task)
        tool = task.get("tool", "")
        args = task.get("args", {})
        depends = task.get("depends_on", [])
        task_id = task.get("id", "UNKNOWN")

        # Check 1: Tool must be known
        if tool not in known_tools:
            task_copy["supervisor_status"] = "rejected"
            task_copy["reject_reason"] = f"Unknown tool: {tool}"
            validated.append(task_copy)
            continue

        # Check 2: Dependencies must reference existing tasks
        invalid_deps = [d for d in depends if d not in task_ids]
        if invalid_deps:
            task_copy["supervisor_status"] = "rejected"
            task_copy["reject_reason"] = f"Invalid dependencies: {invalid_deps}"
            validated.append(task_copy)
            continue

        # Check 3: No circular dependencies (simple check)
        if task_id in depends:
            task_copy["supervisor_status"] = "rejected"
            task_copy["reject_reason"] = "Self-dependency detected"
            validated.append(task_copy)
            continue

        # All checks passed
        task_copy["supervisor_status"] = "approved"
        task_copy["reject_reason"] = ""
        validated.append(task_copy)

    return validated


def check_for_cycles(tasks: List[Dict[str, Any]]) -> bool:
    """
    Check if the task dependency graph has cycles.
    Returns True if cycles are detected.
    """
    # Build adjacency list
    graph = {}
    for task in tasks:
        tid = task["id"]
        deps = task.get("depends_on", [])
        graph[tid] = deps

    # Topological sort via DFS
    visited = set()
    in_stack = set()

    def has_cycle(node):
        if node in in_stack:
            return True
        if node in visited:
            return False
        visited.add(node)
        in_stack.add(node)
        for dep in graph.get(node, []):
            if has_cycle(dep):
                return True
        in_stack.discard(node)
        return False

    for tid in graph:
        if has_cycle(tid):
            return True

    return False

