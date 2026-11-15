"""Specialized agents. Each agent has one responsibility and only its own tools."""
from __future__ import annotations

from . import data, logic
from .errors import InvalidInputError, PermanentError, ValidationFailedError
from .observability import now_iso
from .state import WorkflowState
from .tools import ToolRegistry

AGENT_NAMES = ["Planner Agent", "Router Agent", "Search Agent A", "Search Agent B", "Search Agent C",
               "Filter Agent", "Comparison Agent", "Ranking Agent", "Validator Agent", "Supervisor Agent"]

AGENT_RESPONSIBILITIES = {
    "Planner Agent": "Understand query, extract structured requirements, build dependency-aware plan",
    "Router Agent": "Assign each task to the right specialist; derive sequential/parallel execution levels",
    "Search Agent A": "Obtain candidates from source A (Official Brand Store API)",
    "Search Agent B": "Obtain candidates from source B (Marketplace Catalog)",
    "Search Agent C": "Obtain candidates from source C (Price Aggregator Feed)",
    "Filter Agent": "Apply hard constraints and remove non-compliant products",
    "Comparison Agent": "Compare qualifying products across parameters",
    "Ranking Agent": "Score and sort products with transparent, requirement-aware logic",
    "Validator Agent": "Checkpoint validation of requirements, filtering and final recommendation",
    "Supervisor Agent": "Synchronize parallel outputs, monitor workflow, handle failures, escalate to human",
}


class BaseAgent:
    name = "Base Agent"

    def __init__(self, state: WorkflowState, registry: ToolRegistry | None):
        self.state = state
        self.registry = registry
        self.tools_used: list[str] = []

    def call_tool(self, tool: str, **args):
        self.tools_used.append(tool)
        if self.registry is None:
            raise PermanentError(f"{self.name} has no tool registry")
        return self.registry.call(self.name, tool, **args)

    def send(self, receiver: str, task: str, input_summary: str, output_summary: str, status: str = "SUCCESS"):
        self.state.add_message(self.name, receiver, task, input_summary, output_summary, status)


# ===================================================================== planner
def build_plan(requirements: dict) -> dict:
    cat = requirements["category"]
    tasks = [{"task_id": f"T{i}", "type": "search", "source": src,
              "description": f"Search {data.SOURCES[src]['name']} for {cat} candidates", "depends_on": []}
             for i, src in enumerate(data.SOURCES, 1)]
    tasks += [
        {"task_id": "T4", "type": "synchronize", "description": "Synchronize parallel search results & resolve conflicts",
         "depends_on": ["T1", "T2", "T3"], "allow_partial": True},
        {"task_id": "T5", "type": "filter", "description": "Apply budget/RAM/storage/rating constraints", "depends_on": ["T4"]},
        {"task_id": "T6", "type": "validate_checkpoint", "description": "Checkpoint: verify filtered products", "depends_on": ["T5"]},
        {"task_id": "T7", "type": "compare", "description": "Compare qualifying products", "depends_on": ["T6"]},
        {"task_id": "T8", "type": "rank", "description": "Score and sort products", "depends_on": ["T7"]},
        {"task_id": "T9", "type": "validate", "description": "Validate final recommendation", "depends_on": ["T8"]},
        {"task_id": "T10", "type": "supervise", "description": "Supervise workflow & escalate for human approval",
         "depends_on": ["T9"], "always_run": True},
    ]
    return {"tasks": tasks, "created_at": now_iso()}


class PlannerAgent(BaseAgent):
    name = "Planner Agent"

    def run(self, query: str, overrides: dict | None, excluded: list | None) -> str:
        parsed = self.call_tool("query_parser", query=query)
        req = parsed["requirements"]
        if overrides:
            bad = set(overrides) - set(logic.OVERRIDABLE_KEYS)
            if bad:
                raise InvalidInputError(f"Override keys not permitted: {sorted(bad)}")
            req.update(overrides)
            logic.validate_requirement_values(req)
            self.state.add_message("Human Reviewer", self.name, "Authorized requirement override",
                                   str(overrides), "Applied before requirements were locked")
        if excluded:
            req["excluded_product_ids"] = sorted(set(excluded))
        self.state.write(self.name, "requirements", req)
        self.state.write(self.name, "security_flags", parsed["security_flags"])
        plan = build_plan(req)
        plan["sanitized_query"] = parsed["sanitized_query"]
        plan["removed_clauses"] = parsed["removed_clauses"]
        self.state.write(self.name, "plan", plan)
        n = sum(req.get(k) is not None for k in ("max_price", "min_ram_gb", "min_storage_gb", "min_rating"))
        summary = ", ".join(f"{r['Requirement']}={r['Value']}" for r in logic.describe_requirements(req))
        self.send("Router Agent", "Execution plan", query[:120], f"{summary}; {len(plan['tasks'])} tasks")
        flag_note = f"; {len(parsed['security_flags'])} injection clause(s) neutralized" if parsed["security_flags"] else ""
        return f"{n} constraints extracted, {len(plan['tasks'])} tasks planned{flag_note}"


# ====================================================================== router
ROUTING_TABLE = {
    "search": lambda t: f"Search Agent {t['source']}",
    "synchronize": lambda t: "Supervisor Agent",
    "filter": lambda t: "Filter Agent",
    "validate_checkpoint": lambda t: "Validator Agent",
    "compare": lambda t: "Comparison Agent",
    "rank": lambda t: "Ranking Agent",
    "validate": lambda t: "Validator Agent",
    "supervise": lambda t: "Supervisor Agent",
}


def dependency_levels(tasks: list[dict]) -> list[list[str]]:
    """Kahn's topological sort grouped into levels of mutually independent tasks."""
    ids = [t["task_id"] for t in tasks]
    deps = {t["task_id"]: set(t["depends_on"]) for t in tasks}
    for tid, ds in deps.items():
        missing = ds - set(ids)
        if missing:
            raise PermanentError(f"Task {tid} depends on unknown task(s) {sorted(missing)}")
    done: set[str] = set()
    levels = []
    while len(done) < len(ids):
        level = [tid for tid in ids if tid not in done and deps[tid] <= done]
        if not level:
            raise PermanentError("Cyclic task dependencies detected in plan")
        levels.append(level)
        done.update(level)
    return levels


class RouterAgent(BaseAgent):
    name = "Router Agent"

    def run(self, mode: str) -> str:
        plan = self.state.read("plan")
        tasks = plan["tasks"]
        assignments = {}
        for t in tasks:
            route = ROUTING_TABLE.get(t["type"])
            if route is None:
                raise PermanentError(f"No agent registered for task type '{t['type']}'")
            assignments[t["task_id"]] = route(t)
        levels = dependency_levels(tasks)
        strategy = []
        for i, lvl in enumerate(levels):
            parallel = mode == "parallel" and len(lvl) > 1
            strategy.append({
                "level": i, "tasks": lvl, "agents": [assignments[t] for t in lvl],
                "execution": "parallel" if parallel else "sequential",
                "reason": ("Independent tasks (no mutual dependencies) → run concurrently, then synchronize"
                           if parallel else
                           ("Parallel-capable but sequential mode selected" if len(lvl) > 1
                            else "Depends on previous level output → sequential")),
            })
        self.state.write(self.name, "routing", {"assignments": assignments, "levels": levels, "strategy": strategy, "mode": mode})
        for t in tasks:
            self.send(assignments[t["task_id"]], f"{t['task_id']}: {t['type']}", t["description"],
                      f"Assigned (depends on {t['depends_on'] or 'nothing'})")
        n_par = sum(1 for s in strategy if s["execution"] == "parallel")
        return f"{len(tasks)} tasks routed into {len(levels)} levels ({n_par} parallel)"


# ====================================================================== search
class SearchAgent(BaseAgent):
    def __init__(self, state, registry, source: str):
        super().__init__(state, registry)
        self.source = source
        self.name = f"Search Agent {source}"

    def run(self) -> str:
        req = self.state.get_requirements()
        products = self.call_tool("product_search", source=self.source, category=req["category"])
        self.state.write(self.name, "search_results", products, key=self.source)
        self.state.incr("processing_ops", len(products))
        self.send("Supervisor Agent", "Search results", f"source={self.source}, category={req['category']}",
                  f"{len(products)} candidate product(s)")
        return f"{len(products)} candidates from {data.SOURCES[self.source]['name']}"


# ====================================================================== filter
class FilterAgent(BaseAgent):
    name = "Filter Agent"

    def run(self) -> str:
        req = self.state.get_requirements()
        products = self.state.read("synchronized_results")
        out = self.call_tool("filter_products", products=products, requirements=req)
        self.state.write(self.name, "filtered_results", out["passed"])
        self.state.write(self.name, "rejected_products", out["rejected"])
        self.state.incr("processing_ops", len(products))
        for r in out["rejected"]:
            missing = [x for x in r["reasons"] if x.startswith("Missing product information")]
            if missing:
                self.state.add_error(self.name, "MISSING_PRODUCT_INFORMATION",
                                     f"{r['product_id']} {r['name']}: {'; '.join(missing)}", recoverable=True,
                                     task_id="T5", severity="WARNING")
        self.send("Validator Agent", "Filtered results", f"{len(products)} products",
                  f"{len(out['passed'])} passed, {len(out['rejected'])} rejected")
        return f"{len(out['passed'])} passed / {len(out['rejected'])} rejected"


# ================================================================== comparison
class ComparisonAgent(BaseAgent):
    name = "Comparison Agent"

    def run(self) -> str:
        req = self.state.get_requirements()
        products = self.state.read("filtered_results")
        out = self.call_tool("compare_products", products=products, requirements=req)
        self.state.write(self.name, "comparison", out)
        self.state.incr("processing_ops", len(products))
        self.send("Ranking Agent", "Comparison", f"{len(products)} products", f"best_in={out['best_in']}")
        return f"Compared {len(products)} products"


# ===================================================================== ranking
class RankingAgent(BaseAgent):
    name = "Ranking Agent"

    def run(self) -> str:
        req = self.state.get_requirements()
        products = self.state.read("filtered_results")
        if self.state.read("comparison") is None:
            raise PermanentError("Comparison output not available")
        ranking = self.call_tool("score_products", products=products, requirements=req)
        self.state.write(self.name, "ranking", ranking)
        self.state.incr("processing_ops", len(products))
        top = f"#1 {ranking[0]['name']} ({ranking[0]['score']})" if ranking else "no products"
        self.send("Validator Agent", "Ranked products", f"{len(products)} products", top)
        return f"Ranked {len(ranking)} products; {top}"


# =================================================================== validator
class ValidatorAgent(BaseAgent):
    name = "Validator Agent"

    def checkpoint_requirements(self) -> str:
        req = self.state.get_requirements()
        res = self.call_tool("validate_requirements", requirements=req)
        self.state.write(self.name, "validation", res, key="checkpoint_requirements")
        self.send("Supervisor Agent", "Checkpoint: Query Decomposition", "requirements", "PASSED" if res["passed"] else "FAILED",
                  "SUCCESS" if res["passed"] else "FAILED")
        if not res["passed"]:
            raise ValidationFailedError("Requirement checkpoint failed")
        return "Requirements checkpoint passed"

    def checkpoint_filter(self) -> str:
        req = self.state.get_requirements()
        filtered = self.state.read("filtered_results")
        res = self.call_tool("validate_filtered", filtered=filtered, requirements=req)
        self.state.write(self.name, "validation", res, key="checkpoint_filter")
        self.state.incr("processing_ops", len(filtered))
        self.send("Comparison Agent", "Checkpoint: Product Filtering", f"{len(filtered)} products",
                  "PASSED" if res["passed"] else "FAILED", "SUCCESS" if res["passed"] else "FAILED")
        if not res["passed"]:
            raise ValidationFailedError("Filtering checkpoint failed: non-compliant product passed the filter")
        return f"Filtering checkpoint passed ({len(filtered)} products)"

    def validate_final(self) -> str:
        integrity = self.state.verify_integrity()
        req = self.state.read("requirements")
        ranking = self.state.read("ranking")
        filtered = self.state.read("filtered_results")
        res = self.call_tool("validate_recommendation", ranking=ranking, filtered=filtered,
                             requirements=req, integrity_ok=integrity)
        self.state.write(self.name, "validation", res, key="final")
        self.state.incr("processing_ops", len(ranking))
        failed = [c for c in res["checks"] if not c["passed"]]
        self.send("Supervisor Agent", "Final validation", f"{len(ranking)} ranked products",
                  "PASSED" if res["passed"] else f"FAILED ({len(failed)} check(s))",
                  "SUCCESS" if res["passed"] else "FAILED")
        if not res["passed"]:
            raise ValidationFailedError(f"Final validation failed: {failed[0]['check']}")
        return f"All {len(res['checks'])} validation checks passed"


# ================================================================== supervisor
class SupervisorAgent(BaseAgent):
    name = "Supervisor Agent"

    def synchronize(self) -> str:
        results = self.state.read("search_results")
        if not results:
            raise PermanentError("No search results available to synchronize (all sources failed)")
        out = self.call_tool("synchronize_results", results_by_source=results)
        self.state.write(self.name, "synchronized_results", out["products"])
        self.state.write(self.name, "conflicts", out["conflicts"])
        self.state.incr("processing_ops", sum(len(v) for v in results.values()))
        missing_sources = sorted(set(data.SOURCES) - set(results))
        note = f"; missing sources {missing_sources}" if missing_sources else ""
        self.send("Filter Agent", "Synchronized candidates", f"{len(results)}/3 sources",
                  f"{len(out['products'])} unique products, {len(out['conflicts'])} conflict(s) resolved{note}")
        return f"Barrier reached ({len(results)}/3 sources): {len(out['products'])} unique, {len(out['conflicts'])} conflicts{note}"

    def supervise(self) -> str:
        st = self.state
        integrity = st.verify_integrity()
        task_status = st.read("task_status")
        failed = sorted(t for t, s in task_status.items() if s == "FAILED")
        skipped = sorted(t for t, s in task_status.items() if s == "SKIPPED")
        plan = st.read("plan")
        search_ids = {t["task_id"]: t["source"] for t in (plan or {}).get("tasks", []) if t["type"] == "search"}
        degraded = [search_ids[t] for t in failed if t in search_ids]
        validation = st.read("validation").get("final")
        filtered = st.read("filtered_results")
        conflicts = st.read("conflicts")
        flags = st.read("security_flags")
        metrics = st.read("metrics")

        if not integrity:
            status, action = "BLOCKED_SECURITY", "BLOCK"
            summary = "Shared-state integrity violation detected; recommendation blocked."
        elif plan is None:
            status, action = "FAILED", "ABORT"
            summary = "Planning failed (invalid input); no recommendation produced."
        elif task_status.get("T4") != "SUCCESS":
            status, action = "FAILED", "ABORT"
            summary = "No product data could be obtained from any catalog source."
        elif task_status.get("T5") == "SUCCESS" and not filtered:
            status, action = "NO_RESULTS", "ESCALATE_TO_HUMAN"
            summary = "No product satisfies all constraints. Reviewer may request re-analysis with relaxed requirements."
        elif not validation or not validation["passed"]:
            status, action = "VALIDATION_FAILED", "ESCALATE_TO_HUMAN"
            summary = "Validator rejected the result; it cannot be approved as-is."
        else:
            status, action = "AWAITING_HUMAN_APPROVAL", "ESCALATE_TO_HUMAN"
            summary = "Validated recommendation ready; awaiting human approval."

        reasons = ["Governance policy: every recommendation requires human approval before publication"]
        high = [c for c in conflicts if c["severity"] == "HIGH"]
        if high:
            reasons.append(f"{len(high)} high-severity data conflict(s) resolved via trusted-source priority: "
                           + ", ".join(f"{c['name']} {c['field']} {c['values']}" for c in high))
        if flags:
            reasons.append(f"{len(flags)} prompt-injection clause(s) detected and neutralized")
        if degraded:
            reasons.append(f"Degraded mode: catalog source(s) {degraded} failed")
        if metrics.get("retries"):
            reasons.append(f"{metrics['retries']} controlled retr{'y' if metrics['retries'] == 1 else 'ies'} occurred")
        decision = {"status": status, "action": action, "summary": summary, "escalation_reasons": reasons,
                    "failed_tasks": failed, "skipped_tasks": skipped, "degraded_sources": degraded,
                    "integrity_ok": integrity, "approval_allowed": status == "AWAITING_HUMAN_APPROVAL",
                    "ts": now_iso()}
        st.write(self.name, "supervisor_decision", decision)
        st.write(self.name, "status", status)
        self.send("Human Reviewer", "Escalation", f"failed={failed}, skipped={skipped}", f"{status}: {summary}",
                  "SUCCESS" if status == "AWAITING_HUMAN_APPROVAL" else "ATTENTION")
        return f"{status}"

    def finalize(self, approval: dict) -> str:
        decision = approval["decision"]
        if decision == "APPROVE":
            ranking = self.state.read("ranking")
            validation = self.state.read("validation").get("final", {})
            top = ranking[0]
            final = {
                "top_pick": {k: top[k] for k in ("product_id", "name", "brand", "price", "ram_gb", "storage_gb", "rating", "score")},
                "alternatives": [{k: r[k] for k in ("rank", "product_id", "name", "price", "score")} for r in ranking[1:5]],
                "reasoning": top["reasons"],
                "validation_passed": validation.get("passed", False),
                "approved_by": approval["reviewer"], "approved_at": approval["timestamp"],
            }
            self.state.write(self.name, "final_recommendation", final)
            self.state.write(self.name, "status", "COMPLETED")
            self.send("Customer", "Final recommendation", "human approved", f"{top['name']} ({logic.fmt_inr(top['price'])})")
            return "COMPLETED"
        if decision == "REJECT":
            self.state.write(self.name, "status", "REJECTED")
            self.send("Customer", "Final recommendation", "human rejected", "No recommendation published", "REJECTED")
            return "REJECTED"
        self.state.write(self.name, "status", "REANALYSIS_REQUESTED")
        return "REANALYSIS_REQUESTED"
