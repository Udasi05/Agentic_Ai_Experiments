"""
Custom MCP Server — exposes four review tools via FastMCP.
Tools: analyze_python, scan_secrets, search_code, run_tests
All file access is restricted to the project folder.
"""

import json
import ast
import re
import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Optional, List

try:
    from mcp.server.fastmcp import FastMCP  # type: ignore
except (ImportError, ModuleNotFoundError):
    try:
        from fastmcp import FastMCP  # type: ignore
    except (ImportError, ModuleNotFoundError):
        try:
            from mcp.server.mcpserver import MCPServer as FastMCP  # type: ignore
        except (ImportError, ModuleNotFoundError):
            class FastMCP:  # Fallback for static type checkers if mcp is in another interpreter
                def __init__(self, name: str):
                    self.name = name
                def tool(self):
                    return lambda fn: fn
                def run(self):
                    pass

ROOT = Path(__file__).resolve().parent.parent / "sample_project"

mcp = FastMCP("PR Review Server")


def safe_path(rel: str) -> Path:
    """Resolve a relative path and ensure it's inside the project root."""
    full = (ROOT / rel).resolve()
    if full != ROOT and ROOT not in full.parents:
        raise PermissionError(f"[security] Path outside project: {rel}")
    return full


def _analyze(file: str) -> dict:
    """Analyze a single Python file for code quality issues."""
    path = safe_path(file)
    if not path.exists():
        raise FileNotFoundError(f"[input] File not found: {file}")
    if path.suffix != ".py":
        return {"file": file, "issues": [], "summary": "Not a Python file"}

    source = path.read_text(encoding="utf-8")
    issues = []

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return {
            "file": file,
            "issues": [{
                "rule": "syntax-error",
                "type": "syntax_error",
                "severity": "HIGH",
                "message": str(e),
                "line": e.lineno,
            }],
            "summary": "Syntax error in file",
        }

    # Check for functions without docstrings
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            has_doc = (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, (ast.Constant,))
                and isinstance(node.body[0].value.value, str)
            )
            if not has_doc:
                issues.append({
                    "rule": "missing-docstring",
                    "type": "missing_docstring",
                    "severity": "LOW",
                    "message": f"{node.name} has no docstring",
                    "line": node.lineno,
                })

    # Check for bare excepts
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            issues.append({
                "rule": "bare-except",
                "type": "bare_except",
                "severity": "MEDIUM",
                "message": "Bare except clause",
                "line": node.lineno,
            })

    # Check for long functions (> 50 lines)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if hasattr(node, "end_lineno") and node.end_lineno:
                length = node.end_lineno - node.lineno
                if length > 50:
                    issues.append({
                        "rule": "long-function",
                        "type": "long_function",
                        "severity": "MEDIUM",
                        "message": f"Function '{node.name}' is {length} lines long",
                        "line": node.lineno,
                    })

    # Sort issues by line number
    issues.sort(key=lambda x: x.get("line", 0))

    return {
        "file": file,
        "issues": issues,
        "summary": f"{len(issues)} issue(s) found" if issues else "No issues found",
    }


def _scan(files: Optional[List[str]] = None) -> dict:
    """Scan files for hardcoded credentials and API keys."""
    secret_patterns = [
        (r'(?i)(api[_-]?key|apikey)\s*=\s*["\']([^"\']{8,})["\']', "API Key"),
        (r'(?i)(db[_-]?password|password|passwd|pwd)\s*=\s*["\']([^"\']{4,})["\']', "DB Password"),
        (r'(?i)(secret[_-]?key|secretkey)\s*=\s*["\']([^"\']{8,})["\']', "Secret Key"),
        (r'(?i)(token)\s*=\s*["\']([^"\']{8,})["\']', "Token"),
    ]

    if files is None:
        files = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*.py") if "tests" not in p.parts]

    findings = []
    for f in files:
        try:
            path = safe_path(f)
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            for pattern, label in secret_patterns:
                for match in re.finditer(pattern, content):
                    line_no = content[:match.start()].count('\n') + 1
                    secret_val = match.group(2)
                    masked = secret_val[:6] + "***" if len(secret_val) >= 6 else secret_val[:3] + "***"
                    findings.append({
                        "file": f.replace("\\", "/"),
                        "rule": "Hardcoded-credential",
                        "type": label,
                        "severity": "HIGH",
                        "line": line_no,
                        "message": f"Possible secret: {masked}",
                        "raw_match": match.group(0),
                    })
        except PermissionError:
            continue

    # Sort findings by file and line
    findings.sort(key=lambda x: (x.get("file", ""), x.get("line", 0)))

    return {
        "files_scanned": len(files),
        "secrets_found": len(findings),
        "findings": findings,
    }


def _search(pattern: str, file_glob: str = "*.py") -> dict:
    """Search for a regex pattern across project files."""
    matches = []
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return {"error": f"[input] Invalid regex: {e}", "matches": []}

    for path in ROOT.rglob(file_glob):
        try:
            safe_path(str(path.relative_to(ROOT)))
            content = path.read_text(encoding="utf-8")
            for i, line in enumerate(content.splitlines(), 1):
                if compiled.search(line):
                    matches.append({
                        "file": str(path.relative_to(ROOT)).replace("\\", "/"),
                        "line": i,
                        "content": line.strip(),
                    })
        except (PermissionError, UnicodeDecodeError):
            continue

    return {"pattern": pattern, "file_glob": file_glob, "matches": matches}


def _run_tests(test_path: str = "tests/") -> dict:
    """Run pytest on the specified test path."""
    full_path = safe_path(test_path)
    if not full_path.exists():
        raise FileNotFoundError(f"[input] Test path not found: {test_path}")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(full_path), "-v", "--tb=short", "--no-header", "-p", "no:cacheprovider"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(ROOT),
        )

        output = result.stdout + result.stderr

        passed_m = re.search(r"(\d+)\s+passed", output)
        failed_m = re.search(r"(\d+)\s+failed", output)
        errors_m = re.search(r"(\d+)\s+error", output)

        passed = int(passed_m.group(1)) if passed_m else 0
        failed = int(failed_m.group(1)) if failed_m else 0
        errors = int(errors_m.group(1)) if errors_m else 0

        # Extract specific assertion failure if any
        failure_msg = ""
        fail_match = re.search(r"FAILED\s+[^:]+::(\w+)\s*-\s*(.+)", output)
        if fail_match:
            failure_msg = fail_match.group(2).strip()
        elif failed > 0:
            assert_match = re.search(r"E\s+(assert\s+.+)", output)
            if assert_match:
                failure_msg = assert_match.group(1).strip()
            else:
                failure_msg = f"{failed} test(s) failed"

        return {
            "test_path": test_path,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "total": passed + failed + errors,
            "failure_message": failure_msg,
            "output": output[-2000:] if len(output) > 2000 else output,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"[timeout] Tests timed out after 30 seconds")


# ── FastMCP Tool Definitions ──────────────────────────────────────────────

@mcp.tool()
async def analyze_python(file: str) -> str:
    """AST analysis: missing docstrings, long functions, bare except, syntax errors. Risk: LOW."""
    return json.dumps(await asyncio.to_thread(_analyze, file))


@mcp.tool()
async def scan_secrets(files: Optional[List[str]] = None) -> str:
    """Scan files for hardcoded credentials and API keys. Risk: LOW."""
    return json.dumps(await asyncio.to_thread(_scan, files))


@mcp.tool()
async def search_code(pattern: str, file_glob: str = "*.py") -> str:
    """Regex search over Python source files. Risk: LOW."""
    return json.dumps(await asyncio.to_thread(_search, pattern, file_glob))


@mcp.tool()
async def run_tests(test_path: str = "tests/") -> str:
    """Run pytest in the project directory with a timeout. Risk: MEDIUM."""
    return json.dumps(await asyncio.to_thread(_run_tests, test_path))


if __name__ == "__main__":
    if hasattr(mcp, "run"):
        mcp.run()
    else:
        asyncio.run(mcp.run_stdio_async())
