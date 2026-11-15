"""Policy layer — classifies tool risk and blocks HIGH-risk tools."""

import re

# Explicit risk mapping for known tools
RISK = {
    # Custom PR Review Server tools
    "analyze_python": "LOW",
    "scan_secrets": "LOW",
    "search_code": "LOW",
    "run_tests": "MEDIUM",
    # Git read-only tools
    "git_status": "LOW",
    "git_diff_unstaged": "LOW",
    "git_diff_staged": "LOW",
    "git_diff": "LOW",
    "git_log": "LOW",
    "git_show": "LOW",
    # Git write tools
    "git_commit": "HIGH",
    "git_add": "HIGH",
    "git_reset": "HIGH",
    "git_checkout": "HIGH",
    "git_create_branch": "MEDIUM",
    "git_list_branches": "LOW",
    # Filesystem read tools
    "read_file": "LOW",
    "read_multiple_files": "LOW",
    "list_directory": "LOW",
    "directory_tree": "LOW",
    "search_files": "LOW",
    "get_file_info": "LOW",
    "list_allowed_directories": "LOW",
    # Filesystem write tools
    "write_file": "HIGH",
    "edit_file": "HIGH",
    "create_directory": "HIGH",
    "move_file": "HIGH",
    "delete_file": "HIGH",
}

# Patterns to classify unknown tools
WRITE = re.compile(r"(write|edit|commit|add|delete|remove|create|move|push|reset|checkout)", re.I)
READ = re.compile(r"^(read|list|get|search|scan|analyze|diff|status|log|show|tree|find|count)")


def risk_of(tool: str) -> str:
    """Return the risk level of a tool: LOW, MEDIUM, or HIGH."""
    if tool in RISK:
        return RISK[tool]
    if WRITE.search(tool):
        return "HIGH"
    return "LOW" if READ.match(tool) else "MEDIUM"


def policy_check(tool: str) -> tuple:
    """
    Check if a tool is allowed by policy.
    Returns (risk_level, is_allowed, reason).
    """
    risk = risk_of(tool)
    allowed = risk != "HIGH"
    reason = "" if allowed else "HIGH-risk tools are not permitted"
    return risk, allowed, reason

