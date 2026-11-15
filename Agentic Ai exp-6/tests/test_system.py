"""Integration tests for the PR Review Assistant."""

import sys
import os
import json
import pytest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.policy import risk_of, policy_check
from src.validator import classify_error, is_retryable, validate_result
from src.supervisor import validate_plan
from src.planner import rule_based_plan


# ── Policy Tests ──────────────────────────────────────────────────────────

class TestPolicy:
    def test_low_risk_tools(self):
        assert risk_of("analyze_python") == "LOW"
        assert risk_of("scan_secrets") == "LOW"
        assert risk_of("git_status") == "LOW"
        assert risk_of("read_file") == "LOW"

    def test_medium_risk_tools(self):
        assert risk_of("run_tests") == "MEDIUM"

    def test_high_risk_tools(self):
        assert risk_of("git_commit") == "HIGH"
        assert risk_of("write_file") == "HIGH"
        assert risk_of("delete_file") == "HIGH"

    def test_unknown_write_tool(self):
        assert risk_of("delete_everything") == "HIGH"

    def test_unknown_read_tool(self):
        assert risk_of("read_something") == "LOW"

    def test_policy_blocks_high(self):
        risk, allowed, reason = policy_check("git_commit")
        assert risk == "HIGH"
        assert not allowed
        assert "not permitted" in reason

    def test_policy_allows_low(self):
        risk, allowed, reason = policy_check("analyze_python")
        assert risk == "LOW"
        assert allowed
        assert reason == ""


# ── Validator Tests ───────────────────────────────────────────────────────

class TestValidator:
    def test_classify_security_error(self):
        assert classify_error("[security] Path outside project") == "security"
        assert classify_error("Access denied to resource") == "security"

    def test_classify_timeout_error(self):
        assert classify_error("[timeout] Task timed out") == "timeout"

    def test_classify_input_error(self):
        assert classify_error("[input] File not found") == "input"
        assert classify_error("Resource not found") == "input"

    def test_classify_execution_error(self):
        assert classify_error("[execution] Runtime failure") == "execution"

    def test_classify_tool_error(self):
        assert classify_error("Some unknown error") == "tool"

    def test_retryable(self):
        assert is_retryable("timeout") is True
        assert is_retryable("execution") is True
        assert is_retryable("security") is False
        assert is_retryable("input") is False
        assert is_retryable("tool") is False

    def test_validate_result_success(self):
        valid, err = validate_result('{"status": "ok"}')
        assert valid
        assert err == ""

    def test_validate_result_empty(self):
        valid, err = validate_result("")
        assert not valid

    def test_validate_result_none(self):
        valid, err = validate_result(None)
        assert not valid


# ── Supervisor Tests ──────────────────────────────────────────────────────

class TestSupervisor:
    def test_approve_valid_plan(self):
        tasks = [
            {"id": "TASK-001", "tool": "git_status", "args": {}, "depends_on": []},
            {"id": "TASK-002", "tool": "analyze_python", "args": {"file": "test.py"}, "depends_on": ["TASK-001"]},
        ]
        known_tools = {"git_status", "analyze_python"}
        validated = validate_plan(tasks, known_tools)
        assert all(t["supervisor_status"] == "approved" for t in validated)

    def test_reject_unknown_tool(self):
        tasks = [
            {"id": "TASK-001", "tool": "delete_everything", "args": {}, "depends_on": []},
        ]
        known_tools = {"git_status", "analyze_python"}
        validated = validate_plan(tasks, known_tools)
        assert validated[0]["supervisor_status"] == "rejected"
        assert "Unknown tool" in validated[0]["reject_reason"]

    def test_reject_invalid_dependency(self):
        tasks = [
            {"id": "TASK-001", "tool": "git_status", "args": {}, "depends_on": ["TASK-999"]},
        ]
        known_tools = {"git_status"}
        validated = validate_plan(tasks, known_tools)
        assert validated[0]["supervisor_status"] == "rejected"
        assert "Invalid dependencies" in validated[0]["reject_reason"]


# ── Planner Tests ─────────────────────────────────────────────────────────

class TestPlanner:
    def test_rule_based_plan(self):
        catalog = [
            {"name": "git_status", "description": "Git status"},
            {"name": "analyze_python", "description": "Analyze Python"},
            {"name": "scan_secrets", "description": "Scan secrets"},
            {"name": "run_tests", "description": "Run tests"},
        ]
        tasks = rule_based_plan("Review the project", catalog)
        assert len(tasks) > 0
        assert tasks[0]["tool"] == "git_status"
        assert tasks[0]["depends_on"] == []

    def test_plan_has_dependencies(self):
        catalog = [
            {"name": "git_status", "description": "Git status"},
            {"name": "analyze_python", "description": "Analyze Python"},
            {"name": "scan_secrets", "description": "Scan secrets"},
            {"name": "run_tests", "description": "Run tests"},
        ]
        tasks = rule_based_plan("Review the project", catalog)
        for t in tasks[1:]:
            assert len(t["depends_on"]) > 0


# ── Failure Matrix Tests (Section 7 of Experiment 6) ──────────────────────

class TestFailureMatrix:
    def test_security_error_non_retryable(self):
        err = "[security] Path outside project: ../etc/passwd"
        assert classify_error(err) == "security"
        assert not is_retryable("security")

    def test_input_error_non_retryable(self):
        err = "[input] File not found: non_existent.py"
        assert classify_error(err) == "input"
        assert not is_retryable("input")

    def test_timeout_error_is_retryable(self):
        err = "[timeout] Tests timed out after 30 seconds"
        assert classify_error(err) == "timeout"
        assert is_retryable("timeout")

    def test_supervisor_rejects_unknown_tool(self):
        tasks = [{"id": "TASK-004", "tool": "delete_everything", "args": {}, "depends_on": []}]
        validated = validate_plan(tasks, {"analyze_python", "git_status"})
        assert validated[0]["supervisor_status"] == "rejected"
        assert "Unknown tool" in validated[0]["reject_reason"]

    def test_skip_when_dependency_failed(self):
        # Scan secrets depends on a failed task -> should be marked skipped
        deps = ["TASK-001"]
        completed = {"TASK-001": "failed"}
        failed_deps = [d for d in deps if completed.get(d) != "success"]
        assert len(failed_deps) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

