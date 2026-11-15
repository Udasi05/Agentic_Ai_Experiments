"""Console run of the full experiment: pipeline + HITL approval + test suites + observation table.

Usage:  python run_cli.py ["your query"] [--auto-approve]
"""
import sys

from ecommerce_agents import apply_human_decision, logic, run_pipeline
from ecommerce_agents.evaluation import (DEFAULT_QUERY, build_observation_table, run_failure_tests,
                                         run_functional_tests, run_performance_comparison, run_security_tests)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # ₹ / → on any Windows console
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    query = args[0] if args else DEFAULT_QUERY
    auto = "--auto-approve" in sys.argv

    state = run_pipeline(query)
    print(f"\nWorkflow {state.workflow_id}  status={state.status}")
    if state.read("requirements"):
        for r in logic.describe_requirements(state.read("requirements")):
            print(f"  {r['Requirement']:<20} {r['Value']}")
    for f in state.read("security_flags"):
        print(f"  [SECURITY] injection clause ignored: {f['clause']}")
    print("\nTrace:")
    for t in state.read("trace"):
        print(f"  {t['step']:>2}. {t['task_id']:<4} {t['agent']:<17} {t['status']:<9} {t['duration_ms']:>8.1f} ms  {t['output_status']}")
    print("\nRanking:")
    for r in state.read("ranking"):
        print(f"  #{r['rank']} {r['name']:<26} {logic.fmt_inr(r['price']):>10}  score {r['score']}")

    if state.status == "AWAITING_HUMAN_APPROVAL":
        ans = "a" if auto else input("\nHuman approval — [a]pprove / [r]eject: ").strip().lower()
        state = apply_human_decision(state, "approve" if ans.startswith("a") else "reject", "CLI Reviewer")
        print(f"Decision applied → {state.status}")

    print("\nRunning performance, functional, failure and security suites…")
    perf = run_performance_comparison(query, runs=2)
    suites = run_functional_tests() + run_failure_tests()
    security = run_security_tests()
    for r in suites + security:
        print(f"  [{r['Result']}] {r['Category']:<10} {r['Test']}")

    print("\nOBSERVATION TABLE")
    for row in build_observation_table(state, perf, security):
        print(f"  {row['Parameter']:<34} {row['Observation']}")


if __name__ == "__main__":
    main()
