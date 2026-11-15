"""LangGraph pipeline: load_rules -> ingest -> validate -> score -> route -> draft -> audit -> END
(with a conditional ``fail`` branch from load_rules / ingest)."""

from __future__ import annotations

import csv
import json
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from . import audit as A
from .audit import AuditLogger
from .config import (
    DEFAULT_DATA_PATH,
    DEFAULT_OUTPUTS_DIR,
    DEFAULT_RULES_PATH,
    REVIEW_PENDING,
    ROUTING_STATUSES,
    SCORE_FIELDS,
    OutputPaths,
    reset_outputs,
)
from .drafts import generate_draft, polish_draft
from .errors import WorkflowError
from .ingestion import count_duplicates, ingest, load_candidates, write_rejected
from .routing import route_decision
from .rules import load_rules
from .scoring import score_candidate


class PipelineState(TypedDict, total=False):
    csv_path: str
    rules_path: str
    polish: bool
    rules: dict
    raw_rows: list
    total_loaded: int
    valid: list
    rejected: list
    scores: list
    routes: list
    drafts: list
    results: list
    error: str | None
    failed_stage: str | None


def build_pipeline_graph(audit: AuditLogger, paths: OutputPaths):
    """Compile the pipeline StateGraph. Resources (audit logger, output paths) are closed over."""

    def load_rules_node(state: PipelineState) -> dict:
        try:
            rules = load_rules(state["rules_path"])
        except WorkflowError as exc:
            return {"error": str(exc), "failed_stage": "load_rules"}
        audit.log(A.RULES_LOADED, rule_version=rules["rule_version"],
                  details=f"weights={json.dumps(rules['criteria'])}; thresholds={json.dumps(rules['thresholds'])}")
        return {"rules": rules, "error": None}

    def ingest_node(state: PipelineState) -> dict:
        try:
            rows = load_candidates(state["csv_path"])
        except WorkflowError as exc:
            return {"error": str(exc), "failed_stage": "ingest"}
        audit.log(A.RECORDS_LOADED, details=f"total_records={len(rows)}",
                  rule_version=state["rules"]["rule_version"])
        return {"raw_rows": rows, "total_loaded": len(rows)}

    def validate_node(state: PipelineState) -> dict:
        valid, rejected = ingest(state["raw_rows"])
        audit.register_sensitive([c["name"] for c in valid] + [c["email"] for c in valid])
        audit.register_sensitive([r.get("name", "") for r in state["raw_rows"]])
        audit.register_sensitive([r.get("email", "") for r in state["raw_rows"]])
        write_rejected(rejected, paths.rejected)
        for r in rejected:
            audit.log(A.RECORD_QUARANTINED, r["candidate_id"], status="INVALID",
                      details=f"row={r['row']}; reason={r['reason']}")
        return {"valid": valid, "rejected": rejected}

    def score_node(state: PipelineState) -> dict:
        return {"scores": [score_candidate(c, state["rules"]) for c in state["valid"]]}

    def route_node(state: PipelineState) -> dict:
        return {"routes": [route_decision(c, s["score"], state["rules"])
                           for c, s in zip(state["valid"], state["scores"])]}

    def draft_node(state: PipelineState) -> dict:
        drafts = []
        for c, r in zip(state["valid"], state["routes"]):
            d = generate_draft(c, r["status"])
            if state.get("polish"):
                d = polish_draft(d, c)
            drafts.append(d)
        return {"drafts": drafts}

    def audit_node(state: PipelineState) -> dict:
        rules = state["rules"]
        rv = rules["rule_version"]
        results = []
        for c, s, r, d in zip(state["valid"], state["scores"], state["routes"], state["drafts"]):
            cid = c["candidate_id"]
            parts = "; ".join(f"{b['criterion']}={b['input']}x{b['weight']}%={b['contribution']}" for b in s["breakdown"])
            audit.log(A.CANDIDATE_SCORED, cid, status=str(s["score"]), rule_version=rv,
                      details=f"score={s['score']}; {parts}")
            audit.log(A.CANDIDATE_ROUTED, cid, status=r["status"], rule_version=rv, details=r["reason"])
            audit.log(A.DRAFT_CREATED, cid, status=r["status"], rule_version=rv,
                      details=f"label={d['label']}; source={d['source']}")
            results.append({
                **c,
                "score": s["score"],
                "breakdown": s["breakdown"],
                "rule_version": rv,
                "proposed_status": r["status"],
                "routing_reason": r["reason"],
                "role_mismatch": r["role_mismatch"],
                "draft": d,
                "review_status": REVIEW_PENDING,
            })
        return {"results": results}

    def fail_node(state: PipelineState) -> dict:
        audit.log(A.WORKFLOW_FAILED, status="FAILED",
                  details=f"stage={state.get('failed_stage')}; error={state.get('error')}")
        return {}

    g = StateGraph(PipelineState)
    for name, fn in (("load_rules", load_rules_node), ("ingest", ingest_node), ("validate", validate_node),
                     ("score", score_node), ("route", route_node), ("draft", draft_node),
                     ("audit", audit_node), ("fail", fail_node)):
        g.add_node(name, fn)
    g.add_edge(START, "load_rules")
    g.add_conditional_edges("load_rules", lambda s: "fail" if s.get("error") else "ingest", ["fail", "ingest"])
    g.add_conditional_edges("ingest", lambda s: "fail" if s.get("error") else "validate", ["fail", "validate"])
    g.add_edge("validate", "score")
    g.add_edge("score", "route")
    g.add_edge("route", "draft")
    g.add_edge("draft", "audit")
    g.add_edge("audit", END)
    g.add_edge("fail", END)
    return g.compile()


# --------------------------------------------------------------------------- persistence
def _jsonable(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def _restore_result(r: dict) -> dict:
    r = dict(r)
    for k in SCORE_FIELDS + ("score",):
        if r.get(k) is not None:
            r[k] = Decimal(str(r[k]))
    r["breakdown"] = [{**b, "input": Decimal(b["input"]), "weight": Decimal(b["weight"]),
                       "contribution": Decimal(b["contribution"])} for b in r.get("breakdown", [])]
    return r


def save_pipeline_results(pipeline: dict, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_jsonable(pipeline), indent=2), encoding="utf-8")
    return p


def load_pipeline_results(outputs_dir: str | Path | None = None) -> dict:
    """Load ``pipeline_results.json`` -> same shape as :func:`run_pipeline`'s return value.
    Raises ``WorkflowError`` if the pipeline has not been run."""
    p = OutputPaths.from_dir(outputs_dir).results_json
    if not p.exists():
        raise WorkflowError(f"No pipeline results found at {p}; run the pipeline first")
    data = json.loads(p.read_text(encoding="utf-8"))
    data["results"] = [_restore_result(r) for r in data.get("results", [])]
    return data


def _write_scored_csv(results: list, path: Path) -> None:
    fields = ["candidate_id", "role", *SCORE_FIELDS, "score", "proposed_status", "routing_reason", "rule_version"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, "") for k in fields})


# --------------------------------------------------------------------------- entry point
def run_pipeline(
    csv_path: str | Path = DEFAULT_DATA_PATH,
    rules_path: str | Path = DEFAULT_RULES_PATH,
    outputs_dir: str | Path = DEFAULT_OUTPUTS_DIR,
    *,
    reset: bool = False,
    polish: bool = False,
    audit: AuditLogger | None = None,
) -> dict:
    """Run the whole pipeline graph. Never raises for workflow problems (returns status FAILED).

    Writes (in ``outputs_dir``): rejected_records.csv, audit_log.csv (append),
    pipeline_results.json, scored_candidates.csv. See docs/API.md for the return shape.
    """
    paths = reset_outputs(outputs_dir) if reset else OutputPaths.from_dir(outputs_dir)
    paths.outputs_dir.mkdir(parents=True, exist_ok=True)
    audit = audit or AuditLogger(paths.audit)
    audit.log(A.RUN_STARTED, details="pipeline run started")
    t0 = time.perf_counter()
    graph = build_pipeline_graph(audit, paths)
    state = graph.invoke({"csv_path": str(csv_path), "rules_path": str(rules_path), "polish": polish})
    elapsed = time.perf_counter() - t0

    if state.get("error"):
        return {
            "status": "FAILED", "error": state["error"], "failed_stage": state.get("failed_stage"),
            "run_id": audit.run_id, "rule_version": (state.get("rules") or {}).get("rule_version", ""),
            "rules": state.get("rules"), "total_loaded": state.get("total_loaded", 0),
            "valid_count": 0, "rejected_count": 0, "duplicates": 0, "rejected": [], "results": [],
            "status_counts": {s: 0 for s in ROUTING_STATUSES}, "drafts_generated": 0,
            "elapsed_seconds": elapsed, "avg_ms_per_record": 0.0,
        }

    results = state["results"]
    rejected = state["rejected"]
    counts = {s: sum(1 for r in results if r["proposed_status"] == s) for s in ROUTING_STATUSES}
    pipeline = {
        "status": "COMPLETED",
        "error": None,
        "failed_stage": None,
        "run_id": audit.run_id,
        "rule_version": state["rules"]["rule_version"],
        "rules": state["rules"],
        "total_loaded": state["total_loaded"],
        "valid_count": len(results),
        "rejected_count": len(rejected),
        "duplicates": count_duplicates(rejected),
        "rejected": rejected,
        "results": results,
        "status_counts": counts,
        "drafts_generated": sum(1 for r in results if r.get("draft")),
        "elapsed_seconds": elapsed,
        "avg_ms_per_record": (elapsed * 1000 / len(results)) if results else 0.0,
    }
    save_pipeline_results(pipeline, paths.results_json)
    _write_scored_csv(results, paths.scored_csv)
    audit.log(A.RUN_COMPLETED, status="COMPLETED", rule_version=pipeline["rule_version"],
              details=(f"total={pipeline['total_loaded']}; valid={pipeline['valid_count']}; "
                       f"quarantined={pipeline['rejected_count']}; "
                       + "; ".join(f"{k}={v}" for k, v in counts.items())))
    return pipeline
