"""Full-run review simulation that reproduces the experiment's expected results."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .audit import AuditLogger
from .config import (
    APPROVE,
    DEFAULT_OUTPUTS_DIR,
    EDIT,
    HOLD,
    MANUAL_REVIEW,
    ROLE_VIEWER,
    SIM_FAILURE_ID,
    SIM_REVIEWER_ID,
    SIM_REVIEWER_ROLE,
    SIM_VIEWER_ID,
    OutputPaths,
)
from .metrics import summarize_reviews
from .notifications import NotificationDispatcher
from .review_graph import build_review_graph, invoke_review

# Scripted decisions (everything else is APPROVE)
SIM_DECISIONS = {
    "C102": {"action": HOLD, "notes": "Awaiting team availability"},
    "C103": {"action": EDIT, "override_status": MANUAL_REVIEW, "reason": "Strong open-source contributions"},
}
SIM_UNAUTHORIZED = {"reviewer_id": SIM_VIEWER_ID, "role": ROLE_VIEWER, "action": APPROVE, "candidate_id": "C104"}


def run_simulation(
    outputs_dir: str | Path = DEFAULT_OUTPUTS_DIR,
    *,
    pipeline: dict | None = None,
    reviewer_id: str = SIM_REVIEWER_ID,
    reviewer_role: str = SIM_REVIEWER_ROLE,
    failure_ids: Iterable[str] = (SIM_FAILURE_ID,),
) -> dict:
    """Simulate the full human review.

    1. ``VIEWER-01`` (viewer) tries APPROVE on C104 -> ACCESS_DENIED (logged, nothing sent).
    2. ``HR-001`` (hr_reviewer) decides every valid candidate in pipeline order:
       C102 HOLD, C103 EDIT -> MANUAL_REVIEW ("Strong open-source contributions"), others APPROVE.
    3. Delivery to every id in ``failure_ids`` always fails -> FAILED after 3 attempts.

    Idempotent on existing outputs: already-sent candidates get ``ALREADY_SENT`` (no new row).
    Returns ``{"results": [review summary dicts, unauthorized attempt first], "summary": summarize_reviews(...)}``.
    """
    paths = OutputPaths.from_dir(outputs_dir)
    if pipeline is None:
        from .pipeline_graph import load_pipeline_results
        pipeline = load_pipeline_results(outputs_dir)
    candidates = pipeline["results"]
    audit = AuditLogger(paths.audit)
    audit.register_sensitive([c.get("name", "") for c in candidates] + [c.get("email", "") for c in candidates])
    dispatcher = NotificationDispatcher(paths.sent, fail_ids=failure_ids)
    graph = build_review_graph(audit, dispatcher, paths.reviews)
    by_id = {c["candidate_id"]: c for c in candidates}

    results = []
    u = SIM_UNAUTHORIZED
    if u["candidate_id"] in by_id:
        results.append(invoke_review(graph, by_id[u["candidate_id"]], u["reviewer_id"], u["role"], u["action"]))
    for c in candidates:
        d = SIM_DECISIONS.get(c["candidate_id"], {"action": APPROVE})
        results.append(invoke_review(graph, c, reviewer_id, reviewer_role, d["action"],
                                     override_status=d.get("override_status"), reason=d.get("reason", ""),
                                     notes=d.get("notes", "")))
    return {"results": results, "summary": summarize_reviews(results)}
