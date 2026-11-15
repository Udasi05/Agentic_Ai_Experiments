"""LangGraph per-decision review graph:
authorize -> apply -> dispatch (self-loop while RETRYING, max 2 retries) -> record -> END,
with ``blocked`` branch from authorize / apply (ACCESS_DENIED / REVIEW_REJECTED, no dispatch)."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from . import audit as A
from .audit import AuditLogger
from .config import (
    ACTIONS,
    APPROVE,
    DEFAULT_OUTPUTS_DIR,
    EDIT,
    HOLD,
    MAX_RETRIES,
    NOTIF_ALREADY_SENT,
    NOTIF_BLOCKED,
    NOTIF_FAILED,
    NOTIF_NOT_REQUIRED,
    NOTIF_RETRYING,
    NOTIF_SENT,
    REQUEST_INFO,
    REVIEW_APPROVED,
    REVIEW_DENIED,
    REVIEW_EDITED,
    REVIEW_INFO_REQUESTED,
    REVIEW_ON_HOLD,
    REVIEW_REJECTED_INPUT,
    ROLE_PERMISSIONS,
    ROUTING_STATUSES,
    OutputPaths,
)
from .drafts import generate_draft
from .errors import DeliveryError, WorkflowError
from .notifications import NotificationDispatcher

REVIEW_FIELDS = ("timestamp", "candidate_id", "reviewer_id", "role", "action", "proposed_status",
                 "final_status", "review_status", "override_reason", "notes", "notification_status", "attempts")


def authorize(role: str, action: str) -> bool:
    """True if ``role`` may perform ``action`` (admin / hr_reviewer: all actions; viewer: none)."""
    return action in ROLE_PERMISSIONS.get(str(role or "").strip().lower(), frozenset())


def access_denied_message(role: str, action: str) -> str:
    return f"Access Denied: Role '{role}' may not perform {action}"


class ReviewState(TypedDict, total=False):
    candidate_id: str
    candidate: dict
    reviewer_id: str
    role: str
    action: str
    override_status: str | None
    reason: str
    notes: str
    draft: dict | None
    blocked: bool
    block_event: str | None
    block_reason: str
    proposed_status: str
    final_status: str
    review_status: str
    notification_status: str
    attempts: int
    max_retries: int


def _append_review(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=REVIEW_FIELDS)
        if new_file:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in REVIEW_FIELDS})


def load_review_decisions(outputs_dir: str | Path | None = None, *, latest_only: bool = False) -> list[dict]:
    """Rows of review_decisions.csv (non-blocked decisions). ``latest_only`` keeps the last row per candidate."""
    p = OutputPaths.from_dir(outputs_dir).reviews
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if latest_only:
        latest: dict[str, dict] = {}
        for r in rows:
            latest[r["candidate_id"]] = r
        rows = list(latest.values())
    return rows


def build_review_graph(audit: AuditLogger, dispatcher: NotificationDispatcher, reviews_path: str | Path):
    reviews_path = Path(reviews_path)

    def who(s: ReviewState) -> dict:
        return {"actor": s.get("reviewer_id", ""), "role": s.get("role", "")}

    def authorize_node(s: ReviewState) -> dict:
        if not authorize(s.get("role", ""), s.get("action", "")):
            return {"blocked": True, "block_event": A.ACCESS_DENIED,
                    "block_reason": access_denied_message(s.get("role", ""), s.get("action", "")),
                    "review_status": REVIEW_DENIED}
        return {"blocked": False}

    def apply_node(s: ReviewState) -> dict:
        action = s["action"]
        proposed = s["proposed_status"]
        if action == APPROVE:
            return {"review_status": REVIEW_APPROVED, "final_status": proposed}
        if action == EDIT:
            override = (s.get("override_status") or "").strip()
            reason = (s.get("reason") or "").strip()
            if override not in ROUTING_STATUSES or not reason:
                why = "EDIT requires a valid override_status" if override not in ROUTING_STATUSES else "EDIT requires a non-empty reason"
                return {"blocked": True, "block_event": A.REVIEW_REJECTED, "block_reason": why,
                        "review_status": REVIEW_REJECTED_INPUT}
            return {"review_status": REVIEW_EDITED, "final_status": override}
        if action == HOLD:
            return {"review_status": REVIEW_ON_HOLD, "final_status": REVIEW_ON_HOLD}
        if action == REQUEST_INFO:
            return {"review_status": REVIEW_INFO_REQUESTED, "final_status": REVIEW_INFO_REQUESTED}
        return {"blocked": True, "block_event": A.REVIEW_REJECTED, "block_reason": f"Unknown action: {action}",
                "review_status": REVIEW_REJECTED_INPUT}

    def dispatch_node(s: ReviewState) -> dict:
        cid = s["candidate_id"]
        if s["action"] != APPROVE:
            return {"notification_status": NOTIF_NOT_REQUIRED}
        attempts = s.get("attempts", 0)
        if attempts == 0 and dispatcher.already_sent(cid):
            audit.log(A.NOTIFICATION_SKIPPED, cid, status=NOTIF_ALREADY_SENT, details="idempotent: already sent", **who(s))
            return {"notification_status": NOTIF_ALREADY_SENT}
        attempts += 1
        draft = s.get("draft")
        if not draft:
            stored = s["candidate"].get("draft")
            draft = stored if stored and stored.get("status") == s["final_status"] else generate_draft(s["candidate"], s["final_status"])
        try:
            dispatcher.send(cid, s["final_status"], draft["subject"], draft["message"], s.get("reviewer_id", ""), attempts)
        except DeliveryError as exc:
            if attempts <= s.get("max_retries", MAX_RETRIES):
                audit.log(A.NOTIFICATION_RETRY, cid, status=NOTIF_RETRYING, details=f"attempt={attempts}; {exc}", **who(s))
                return {"notification_status": NOTIF_RETRYING, "attempts": attempts}
            audit.log(A.NOTIFICATION_FAILED, cid, status=NOTIF_FAILED, details=f"attempts={attempts}; {exc}", **who(s))
            return {"notification_status": NOTIF_FAILED, "attempts": attempts}
        audit.log(A.NOTIFICATION_SENT, cid, status=NOTIF_SENT, details=f"attempts={attempts}", **who(s))
        return {"notification_status": NOTIF_SENT, "attempts": attempts}

    def record_node(s: ReviewState) -> dict:
        cid = s["candidate_id"]
        if s["action"] == EDIT:
            audit.log(A.STATUS_OVERRIDDEN, cid, status=s["final_status"],
                      details=f"{s['proposed_status']} -> {s['final_status']}; reason={s.get('reason', '')}", **who(s))
        audit.log(A.REVIEW_DECISION, cid, status=s["review_status"],
                  details=f"action={s['action']}; final_status={s['final_status']}; notification={s['notification_status']}",
                  **who(s))
        _append_review(reviews_path, {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "candidate_id": cid, "reviewer_id": s.get("reviewer_id", ""), "role": s.get("role", ""),
            "action": s["action"], "proposed_status": s["proposed_status"], "final_status": s["final_status"],
            "review_status": s["review_status"], "override_reason": s.get("reason", "") if s["action"] == EDIT else "",
            "notes": s.get("notes", ""), "notification_status": s["notification_status"],
            "attempts": s.get("attempts", 0),
        })
        return {}

    def blocked_node(s: ReviewState) -> dict:
        audit.log(s["block_event"], s.get("candidate_id", ""), status=s.get("review_status", ""),
                  details=f"action={s.get('action')}; {s.get('block_reason', '')}", **who(s))
        return {"notification_status": NOTIF_BLOCKED, "final_status": s.get("proposed_status", "")}

    g = StateGraph(ReviewState)
    g.add_node("authorize", authorize_node)
    g.add_node("apply", apply_node)
    g.add_node("dispatch", dispatch_node)
    g.add_node("record", record_node)
    g.add_node("blocked", blocked_node)
    g.add_edge(START, "authorize")
    g.add_conditional_edges("authorize", lambda s: "blocked" if s.get("blocked") else "apply", ["blocked", "apply"])
    g.add_conditional_edges("apply", lambda s: "blocked" if s.get("blocked") else "dispatch", ["blocked", "dispatch"])
    g.add_conditional_edges("dispatch", lambda s: "dispatch" if s["notification_status"] == NOTIF_RETRYING else "record",
                            ["dispatch", "record"])
    g.add_edge("record", END)
    g.add_edge("blocked", END)
    return g.compile()


def _find_candidate(candidate_id: str, results: list[dict]) -> dict:
    for r in results:
        if r["candidate_id"] == candidate_id:
            return r
    raise WorkflowError(f"Unknown candidate_id: {candidate_id}")


def invoke_review(graph, candidate: dict, reviewer_id: str, role: str, action: str, *,
                  override_status: str | None = None, reason: str = "", notes: str = "",
                  draft: dict | None = None, max_retries: int = MAX_RETRIES) -> dict:
    """Run one decision through an already-compiled review graph; returns the summary dict."""
    state = graph.invoke({
        "candidate_id": candidate["candidate_id"], "candidate": candidate,
        "reviewer_id": reviewer_id, "role": role, "action": str(action or "").upper(),
        "override_status": override_status, "reason": reason or "", "notes": notes or "",
        "draft": draft, "blocked": False, "block_event": None, "block_reason": "",
        "proposed_status": candidate["proposed_status"], "final_status": candidate["proposed_status"],
        "review_status": "", "notification_status": "", "attempts": 0, "max_retries": max_retries,
    })
    return {
        "candidate_id": candidate["candidate_id"],
        "reviewer_id": reviewer_id,
        "role": role,
        "action": state["action"],
        "blocked": bool(state.get("blocked")),
        "block_event": state.get("block_event"),
        "block_reason": state.get("block_reason", ""),
        "proposed_status": state["proposed_status"],
        "final_status": state.get("final_status", ""),
        "review_status": state.get("review_status", ""),
        "notification_status": state.get("notification_status", ""),
        "attempts": state.get("attempts", 0),
    }


def run_review(
    candidate_id: str,
    reviewer_id: str,
    role: str,
    action: str,
    override_status: str | None = None,
    reason: str = "",
    notes: str = "",
    *,
    outputs_dir: str | Path = DEFAULT_OUTPUTS_DIR,
    results: list[dict] | None = None,
    draft: dict | None = None,
    dispatcher: NotificationDispatcher | None = None,
    simulate_failure: bool = False,
    audit: AuditLogger | None = None,
) -> dict:
    """Process ONE human review decision through the review graph.

    ``results``: pipeline result entries (default: loaded from ``outputs_dir/pipeline_results.json``).
    ``draft``: optional edited ``{"subject", "message"}`` to send instead of the stored draft.
    ``simulate_failure``: every delivery attempt fails (-> FAILED after 3 attempts).
    """
    paths = OutputPaths.from_dir(outputs_dir)
    if results is None:
        from .pipeline_graph import load_pipeline_results
        results = load_pipeline_results(outputs_dir)["results"]
    candidate = _find_candidate(str(candidate_id).strip().upper(), results)
    # A previous EDIT overrides the proposed status for later decisions (e.g. APPROVE after EDIT):
    # use the last recorded routing status for this candidate, if any.
    for row in reversed(load_review_decisions(outputs_dir)):
        if row["candidate_id"] == candidate["candidate_id"] and row["final_status"] in ROUTING_STATUSES:
            if row["final_status"] != candidate["proposed_status"]:
                candidate = {**candidate, "proposed_status": row["final_status"]}
            break
    audit = audit or AuditLogger(paths.audit)
    audit.register_sensitive([r.get("name", "") for r in results] + [r.get("email", "") for r in results])
    dispatcher = dispatcher or NotificationDispatcher(paths.sent, simulate_failure=simulate_failure)
    graph = build_review_graph(audit, dispatcher, paths.reviews)
    return invoke_review(graph, candidate, reviewer_id, role, action, override_status=override_status,
                         reason=reason, notes=notes, draft=draft)


__all__ = ["ACTIONS", "REVIEW_FIELDS", "authorize", "access_denied_message", "build_review_graph",
           "invoke_review", "run_review", "load_review_decisions"]
