"""CLI for the Automated Recruitment Workflow (Experiment 7).

    python recruitment_workflow.py                    # fresh pipeline run (resets outputs/)
    python recruitment_workflow.py --simulate-review  # + full human-review simulation and metrics
    python recruitment_workflow.py --simulate-review --keep-outputs   # re-run on existing outputs (no double send)
"""

from __future__ import annotations

import argparse
import sys

from recruitment.config import DEFAULT_DATA_PATH, DEFAULT_OUTPUTS_DIR, DEFAULT_RULES_PATH
from recruitment.metrics import compute_metrics, format_metrics, run_test_suite
from recruitment.pipeline_graph import run_pipeline
from recruitment.scoring import format_score
from recruitment.simulation import run_simulation


def print_pipeline(pipeline: dict) -> None:
    print(f"Total records loaded: {pipeline['total_loaded']}\n")
    items = [(r["row"], "valid", r) for r in pipeline["results"]] + \
            [(r["row"], "invalid", r) for r in pipeline["rejected"]]
    for _, kind, r in sorted(items, key=lambda x: x[0]):
        if kind == "valid":
            print(f"Candidate ID: {r['candidate_id']}")
            print("Validation: VALID")
            print(f"Score: {format_score(r['score'])}")
            print(f"Proposed Status: {r['proposed_status']}")
            print(f"Notification: {r['draft']['label']}")
            print(f"Human Review: {r['review_status']}\n")
        else:
            print(f"{r['candidate_id']}: INVALID ({r['reason']})\n")
    print(f"Invalid Records: {pipeline['rejected_count']}")
    print(f"Candidates Processed: {pipeline['valid_count']}")
    print(f"Human Reviews Pending: {sum(1 for r in pipeline['results'] if r['review_status'] == 'PENDING')}")
    print("Audit Log: Generated")


def print_table(rows: list[tuple[str, str]]) -> None:
    w = max(len(k) for k, _ in rows)
    v = max(len(x) for _, x in rows)
    print(f"{'Metric'.ljust(w)} | Value")
    print(f"{'-' * w}-+-{'-' * v}")
    for k, x in rows:
        print(f"{k.ljust(w)} | {x}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Automated Recruitment Workflow (LangGraph)")
    ap.add_argument("--data", default=str(DEFAULT_DATA_PATH), help="candidate CSV")
    ap.add_argument("--rules", default=str(DEFAULT_RULES_PATH), help="rules JSON")
    ap.add_argument("--outputs", default=str(DEFAULT_OUTPUTS_DIR), help="outputs directory")
    ap.add_argument("--simulate-review", action="store_true", help="run the human-review simulation + metrics")
    ap.add_argument("--keep-outputs", action="store_true", help="do not reset outputs/ before running")
    ap.add_argument("--polish", action="store_true", help="polish drafts with Gemini (needs GEMINI_API_KEY)")
    ap.add_argument("--run-tests", action="store_true", help="run pytest and include the test pass rate")
    args = ap.parse_args(argv)

    pipeline = run_pipeline(args.data, args.rules, args.outputs, reset=not args.keep_outputs, polish=args.polish)
    if pipeline["status"] != "COMPLETED":
        print(f"WORKFLOW FAILED ({pipeline['failed_stage']}): {pipeline['error']}")
        print("Audit Log: Generated")
        return 1
    print_pipeline(pipeline)

    if args.simulate_review:
        sim = run_simulation(args.outputs, pipeline=pipeline)
        s = sim["summary"]
        print("\n=== Human Review Simulation ===")
        print(f"Decisions: {s['decisions']} (approve {s['approvals']}, hold {s['holds']}, edit {s['edits']}, "
              f"request info {s['info_requests']})")
        print(f"Unauthorized attempts denied: {s['denied']}")
        print(f"Notifications sent: {s['sent']} | failed: {s['failed']}\n")
        tests = run_test_suite() if args.run_tests else None
        print_table(format_metrics(compute_metrics(pipeline, s, test_results=tests)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
