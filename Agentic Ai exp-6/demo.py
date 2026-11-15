"""
PR Review Assistant — Console Demo Runner
Demonstrates the full Experiment 6 pipeline from the terminal.
"""

import asyncio
import json
import time
from pathlib import Path
from src.mcp_client import MCPClient, ALL_30_TOOLS
from src.planner import create_plan
from src.supervisor import validate_plan
from src.policy import policy_check, risk_of
from src.executor import compute_phases, generate_verdict, TaskResult
from src.tracer import Tracer
from src.benchmark import get_experiment_baseline_benchmark


def main():
    print("=" * 70)
    print("  PR REVIEW ASSISTANT (Experiment 6 - Model Context Protocol)")
    print("=" * 70)

    # 1. Multi-Server Tool Discovery
    print("\n[Step 1] Multi-Server Tool Discovery")
    client = MCPClient()
    catalog = client.get_tool_catalog()
    servers = set(t["server"] for t in catalog)
    print(f"  ✓ Connected MCP Servers: {', '.join(sorted(servers))}")
    print(f"  ✓ Total Tools Discovered: {len(catalog)}")
    for srv in sorted(servers):
        tools = [t["name"] for t in catalog if t["server"] == srv]
        print(f"    - {srv} ({len(tools)} tools): {', '.join(tools[:4])}...")

    # 2. Planner Agent
    request = "Review my project before I open a PR"
    print(f"\n[Step 2] Planner Agent (Request: '{request}')")
    tasks, planner_type = create_plan(request, catalog)
    print(f"  ✓ Planner Engine: {planner_type}")
    print(f"  ✓ Generated Tasks ({len(tasks)} tasks):")
    for t in tasks:
        print(f"    - {t['id']}: tool={t['tool']} | server={t.get('server', 'review')} | deps={t.get('depends_on', [])}")

    # 3. Supervisor Agent Validation
    print("\n[Step 3] Supervisor Agent Validation")
    known_tools = {t["name"] for t in catalog}
    validated_tasks = validate_plan(tasks, known_tools)
    for t in validated_tasks:
        print(f"    - {t['id']} [{t['tool']}]: {t['supervisor_status'].upper()}")

    # 4. Policy Layer Check & Execution
    print("\n[Step 4] Dependency-Aware Execution & Policy Enforcement")
    phases = compute_phases(validated_tasks)
    tracer = Tracer()
    task_results = []
    completed = {}

    for phase_num in sorted(phases.keys()):
        phase_tasks = phases[phase_num]
        print(f"\n  ── Phase {phase_num + 1} ({len(phase_tasks)} tasks) ──")

        for task in phase_tasks:
            tid = task["id"]
            tool_name = task["tool"]
            risk, allowed, reason = policy_check(tool_name)

            if not allowed:
                print(f"    🚫 {tid} [{tool_name}]: BLOCKED by Policy ({reason})")
                res = TaskResult(task_id=tid, tool=tool_name, status="BLOCKED", error=reason, risk=risk, phase=phase_num)
                task_results.append(res)
                completed[tid] = "BLOCKED"
                continue

            t0 = time.time()
            output = client._execute_locally(tool_name, task.get("args", {}))
            dur_ms = round((time.time() - t0) * 1000, 1)

            print(f"    ⚡ {tid} [{tool_name}] (Risk: {risk}): OK in {dur_ms}ms")
            res = TaskResult(task_id=tid, tool=tool_name, status="OK", result=output, attempts=1, duration_ms=dur_ms, risk=risk, phase=phase_num)
            task_results.append(res)
            completed[tid] = "OK"
            tracer.log(task_id=tid, tool=tool_name, status="OK", duration_ms=dur_ms)

    # 5. Review Verdict & Report
    print("\n[Step 5] Review Verdict & Report")
    verdict = generate_verdict(task_results)
    print(f"  ========================================")
    print(f"  VERDICT: {verdict['verdict']}")
    print(f"  TRACE ID: {tracer.trace_id}")
    print(f"  ========================================")
    print(f"  Summary: {verdict['summary']}")
    print(f"  Files Reviewed: {verdict['files_reviewed']}")
    print(f"  Issues Found: {verdict['metrics']['total_issues']} ({verdict['metrics']['high']} High, {verdict['metrics']['medium']} Med, {verdict['metrics']['low']} Low)")

    print("\n  Issues Breakdown (Sorted by Severity):")
    print(f"  {'SEVERITY':<8} | {'FILE':<20} | {'LINE':<6} | {'RULE':<22} | {'MESSAGE'}")
    print("  " + "-" * 75)
    for issue in verdict["issues"]:
        print(f"  {issue['severity']:<8} | {issue['file']:<20} | {str(issue['line']):<6} | {issue['rule']:<22} | {issue['message']}")

    # 6. Policy Blocking Demo (Request with mutation)
    print("\n[Step 6] Policy Blocking Demonstration (Request to commit changes)")
    commit_req = "Review the project, then stage and commit all changes with message fix"
    commit_tasks, _ = create_plan(commit_req, catalog)
    print(f"  Planned {len(commit_tasks)} tasks for commit request:")
    for t in commit_tasks:
        risk, allowed, reason = policy_check(t["tool"])
        status = "ALLOWED" if allowed else "BLOCKED by Policy"
        print(f"    - {t['id']} [{t['tool']:<18}] Risk: {risk:<6} -> {status}")

    # 7. Performance Benchmarks
    print("\n[Step 7] Performance Benchmark Summary (Sequential vs. Parallel)")
    bench = get_experiment_baseline_benchmark()
    print("  " + bench["summary_df"].to_string(index=False).replace("\n", "\n  "))

    print("\n" + "=" * 70)
    print("  ALL EXPERIMENT 6 CHECKS COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()

