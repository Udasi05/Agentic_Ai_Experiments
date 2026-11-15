"""Evaluation metrics for the recruitment workflow."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from .config import (
    APPROVE,
    DEFAULT_OUTPUTS_DIR,
    EDIT,
    HOLD,
    MANUAL_REVIEW,
    NOT_SHORTLISTED_REVIEW,
    NOTIF_ALREADY_SENT,
    NOTIF_FAILED,
    NOTIF_SENT,
    PROJECT_ROOT,
    REQUEST_INFO,
    SHORTLIST_REVIEW,
    OutputPaths,
)
from .scoring import check_score_consistency


def pct(numerator: float, denominator: float) -> float:
    return (100.0 * numerator / denominator) if denominator else 0.0


def fmt_pct(value: float | None) -> str:
    """91.666 -> "91.7%", 100.0 -> "100%"; None -> "Not run"."""
    if value is None:
        return "Not run"
    s = f"{value:.1f}"
    if s.endswith(".0"):
        s = s[:-2]
    return s + "%"


def summarize_reviews(review_results: Iterable[dict]) -> dict[str, int]:
    """Aggregate review summary dicts (from run_review / invoke_review).

    Keys: decisions, approvals, edits, holds, info_requests, denied, review_rejected,
    sent (SENT or ALREADY_SENT), failed, reviewed_candidates (unique, non-blocked).
    """
    results = list(review_results)
    done = [r for r in results if not r.get("blocked")]
    approvals = [r for r in done if r["action"] == APPROVE]
    return {
        "decisions": len(done),
        "approvals": len(approvals),
        "edits": sum(1 for r in done if r["action"] == EDIT),
        "holds": sum(1 for r in done if r["action"] == HOLD),
        "info_requests": sum(1 for r in done if r["action"] == REQUEST_INFO),
        "denied": sum(1 for r in results if r.get("block_event") == "ACCESS_DENIED"),
        "review_rejected": sum(1 for r in results if r.get("block_event") == "REVIEW_REJECTED"),
        "sent": sum(1 for r in approvals if r["notification_status"] in (NOTIF_SENT, NOTIF_ALREADY_SENT)),
        "failed": sum(1 for r in approvals if r["notification_status"] == NOTIF_FAILED),
        "reviewed_candidates": len({r["candidate_id"] for r in done}),
    }


def compute_metrics(
    pipeline: dict,
    review_summary: dict | None = None,
    *,
    test_results: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Compute all metrics from a pipeline result (run_pipeline / load_pipeline_results) and an
    optional review summary (summarize_reviews / run_simulation()["summary"]).

    ``test_results``: optional ``(passed, total)`` from :func:`run_test_suite`.
    """
    rs = review_summary or {}
    results = pipeline.get("results", [])
    valid = pipeline.get("valid_count", len(results))
    total = pipeline.get("total_loaded", 0)
    counts = pipeline.get("status_counts", {})
    completed = sum(1 for r in results if r.get("proposed_status") and r.get("draft"))
    rules = pipeline.get("rules")
    identical, checked = check_score_consistency(results, rules) if rules and results else (0, 0)
    m: dict[str, Any] = {
        "total_loaded": total,
        "valid": valid,
        "quarantined": pipeline.get("rejected_count", 0),
        "duplicates": pipeline.get("duplicates", 0),
        "shortlist": counts.get(SHORTLIST_REVIEW, 0),
        "manual": counts.get(MANUAL_REVIEW, 0),
        "not_shortlisted": counts.get(NOT_SHORTLISTED_REVIEW, 0),
        "drafts": pipeline.get("drafts_generated", 0),
        "approvals": rs.get("approvals", 0),
        "holds": rs.get("holds", 0),
        "edits": rs.get("edits", 0),
        "info_requests": rs.get("info_requests", 0),
        "sent": rs.get("sent", 0),
        "failed": rs.get("failed", 0),
        "denied": rs.get("denied", 0),
        "reviewed": rs.get("reviewed_candidates", 0),
        "data_validation_rate": pct(valid, total),
        "workflow_success_rate": pct(completed, valid) if pipeline.get("status") == "COMPLETED" else 0.0,
        "draft_generation_rate": pct(pipeline.get("drafts_generated", 0), valid),
        "human_review_completion_rate": pct(rs.get("reviewed_candidates", 0), valid),
        "avg_processing_ms": float(pipeline.get("avg_ms_per_record", 0.0)),
        "score_identical": identical,
        "score_checked": checked,
        "score_consistent": checked > 0 and identical == checked,
        "tests_passed": test_results[0] if test_results else None,
        "tests_total": test_results[1] if test_results else None,
        "test_pass_rate": pct(*test_results) if test_results else None,
    }
    return m


def format_metrics(m: dict[str, Any]) -> list[tuple[str, str]]:
    """Ordered ``(Metric, Value)`` rows for display (console table / st.dataframe)."""
    tests = (f"{fmt_pct(m['test_pass_rate'])} ({m['tests_passed']}/{m['tests_total']})"
             if m.get("test_pass_rate") is not None else "Not run")
    return [
        ("Records loaded / valid / quarantined", f"{m['total_loaded']} / {m['valid']} / {m['quarantined']}"),
        ("Duplicates", str(m["duplicates"])),
        ("Shortlist / Manual / Not shortlisted", f"{m['shortlist']} / {m['manual']} / {m['not_shortlisted']}"),
        ("Drafts generated", str(m["drafts"])),
        ("Approvals / Holds / Edits", f"{m['approvals']} / {m['holds']} / {m['edits']}"),
        ("Notifications sent / failed", f"{m['sent']} / {m['failed']}"),
        ("Unauthorized attempts denied", str(m["denied"])),
        ("Data validation rate", fmt_pct(m["data_validation_rate"])),
        ("Workflow success rate", fmt_pct(m["workflow_success_rate"])),
        ("Draft generation rate", fmt_pct(m["draft_generation_rate"])),
        ("Human review completion rate", fmt_pct(m["human_review_completion_rate"])),
        ("Avg processing time per valid record", f"{m['avg_processing_ms']:.2f} ms"),
        ("Score consistency on re-run",
         f"{'Identical' if m['score_consistent'] else 'MISMATCH'} ({m['score_identical']}/{m['score_checked']})"),
        ("Test pass rate", tests),
    ]


def review_summary_from_outputs(outputs_dir: str | Path = DEFAULT_OUTPUTS_DIR) -> dict[str, int]:
    """Review summary reconstructed from files (latest decision per candidate,
    sent_notifications.csv, ACCESS_DENIED / REVIEW_REJECTED rows in audit_log.csv)."""
    from .audit import read_audit_log
    from .notifications import load_sent
    from .review_graph import load_review_decisions

    paths = OutputPaths.from_dir(outputs_dir)
    latest = load_review_decisions(outputs_dir, latest_only=True)
    sent_ids = {r["candidate_id"] for r in load_sent(paths.sent)}
    audit_rows = read_audit_log(paths.audit)
    return {
        "decisions": len(latest),
        "approvals": sum(1 for r in latest if r["action"] == APPROVE),
        "edits": sum(1 for r in latest if r["action"] == EDIT),
        "holds": sum(1 for r in latest if r["action"] == HOLD),
        "info_requests": sum(1 for r in latest if r["action"] == REQUEST_INFO),
        "denied": sum(1 for r in audit_rows if r["event"] == "ACCESS_DENIED"),
        "review_rejected": sum(1 for r in audit_rows if r["event"] == "REVIEW_REJECTED"),
        "sent": len(sent_ids),
        "failed": sum(1 for r in latest if r["notification_status"] == NOTIF_FAILED and r["candidate_id"] not in sent_ids),
        "reviewed_candidates": len(latest),
    }


def metrics_from_outputs(outputs_dir: str | Path = DEFAULT_OUTPUTS_DIR, *,
                         test_results: tuple[int, int] | None = None) -> dict[str, Any]:
    """compute_metrics() using only files in ``outputs_dir`` (for the Streamlit Metrics tab)."""
    from .pipeline_graph import load_pipeline_results

    return compute_metrics(load_pipeline_results(outputs_dir), review_summary_from_outputs(outputs_dir),
                           test_results=test_results)


def run_test_suite(tests_dir: str | Path | None = None, timeout: int = 600) -> tuple[int, int]:
    """Run pytest in a subprocess; returns ``(passed, total)``. Do NOT call from inside a test."""
    tests_dir = Path(tests_dir) if tests_dir else PROJECT_ROOT / "tests"
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tests_dir)],
                          capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=timeout)
    out = proc.stdout + proc.stderr
    passed = sum(int(n) for n in re.findall(r"(\d+) passed", out))
    failed = sum(int(n) for n in re.findall(r"(\d+) (?:failed|error|errors)\b", out))
    return passed, passed + failed
