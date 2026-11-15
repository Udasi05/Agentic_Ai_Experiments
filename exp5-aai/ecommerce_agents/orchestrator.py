"""Workflow orchestration: dependency-aware execution, controlled retry, tracing, metrics, HITL."""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from typing import Callable

from .agents import (ComparisonAgent, FilterAgent, PlannerAgent, RankingAgent, RouterAgent, SearchAgent,
                     SupervisorAgent, ValidatorAgent, BaseAgent)
from .errors import AgentExecutionError, AgentSystemError, InvalidInputError, PermanentError, RecoverableError
from .observability import log_event, now_iso
from .state import WorkflowState
from .tools import FailureInjector, ToolRegistry, build_registry

# Experimental cost units (relative, not currency).
COST_WEIGHTS = {"agent_call": 1.0, "tool_call": 2.0, "retry": 3.0, "processing_op": 0.01}


@dataclass
class PipelineConfig:
    mode: str = "parallel"              # "parallel" | "sequential"
    search_latency: float = 0.3         # simulated catalog API latency (s)
    tool_timeout: float = 2.0           # per-call tool timeout (s)
    max_retries: int = 2                # retry budget per agent execution (recoverable errors only)
    retry_backoff: float = 0.05         # linear backoff base (s)
    failures: dict = field(default_factory=dict)   # FailureInjector plan
    requirement_overrides: dict | None = None      # human-authorized overrides (re-analysis)
    excluded_product_ids: list = field(default_factory=list)
    tamper_after_planning: bool = False            # security test hook

    def validate(self) -> None:
        if self.mode not in ("parallel", "sequential"):
            raise InvalidInputError("mode must be 'parallel' or 'sequential'")
        if not 0 <= self.max_retries <= 5:
            raise InvalidInputError("max_retries must be between 0 and 5 (bounded retry)")
        if self.search_latency < 0 or self.tool_timeout <= 0:
            raise InvalidInputError("latency must be >= 0 and timeout > 0")


class Orchestrator:
    def __init__(self, config: PipelineConfig | None = None, search_cache: dict | None = None):
        self.config = config or PipelineConfig()
        self.config.validate()
        self.search_cache = search_cache if search_cache is not None else {}

    # ------------------------------------------------------------ agent wrapper
    def _execute(self, state: WorkflowState, injector: FailureInjector, agent: BaseAgent, task_id: str,
                 task: str, fn: Callable[[BaseAgent], str]) -> str:
        """Run one agent with tracing and controlled retry (recoverable errors only)."""
        attempt = 0
        while True:
            agent.tools_used = []
            start_iso, t_start = now_iso(), state.elapsed_ms()
            state.incr("agent_executions")
            state.mark_agent(agent.name)
            try:
                fault = injector.next_failure(f"agent:{agent.name}")
                if fault == "permanent":
                    raise PermanentError(f"{agent.name} crashed (injected permanent fault)")
                if fault:
                    raise AgentExecutionError(f"{agent.name} crashed (injected transient fault)")
                output_status = fn(agent)
                t_end = state.elapsed_ms()
                state.add_trace(task_id=task_id, agent=agent.name, task=task, start=start_iso, end=now_iso(),
                                t_start_ms=t_start, t_end_ms=t_end, duration_ms=round(t_end - t_start, 2),
                                status="SUCCESS", tools=list(agent.tools_used), attempt=attempt + 1,
                                retries=attempt, error=None, output_status=output_status)
                return output_status
            except RecoverableError as e:
                t_end = state.elapsed_ms()
                will_retry = attempt < self.config.max_retries
                state.add_trace(task_id=task_id, agent=agent.name, task=task, start=start_iso, end=now_iso(),
                                t_start_ms=t_start, t_end_ms=t_end, duration_ms=round(t_end - t_start, 2),
                                status="RETRYING" if will_retry else "FAILED", tools=list(agent.tools_used),
                                attempt=attempt + 1, retries=attempt, error=f"{type(e).__name__}: {e}",
                                output_status="retry scheduled" if will_retry else "retry budget exhausted")
                state.add_error(agent.name, type(e).__name__, str(e), recoverable=True, task_id=task_id,
                                severity="WARNING" if will_retry else "ERROR")
                if will_retry:
                    attempt += 1
                    state.incr("retries")
                    log_event(state.workflow_id, agent.name, "RETRY", task_id=task_id, attempt=attempt + 1)
                    time.sleep(self.config.retry_backoff * attempt)
                    continue
                agent.send("Supervisor Agent", task, f"task {task_id}",
                           f"Failed after {attempt + 1} attempt(s): {e}", "FAILED")
                raise
            except AgentSystemError as e:
                self._record_permanent(state, agent, task_id, task, start_iso, t_start, attempt, e)
                raise
            except Exception as e:  # unexpected defect -> treat as permanent, never crash the workflow
                wrapped = PermanentError(f"Unexpected {type(e).__name__}: {e}")
                self._record_permanent(state, agent, task_id, task, start_iso, t_start, attempt, wrapped)
                raise wrapped from e

    @staticmethod
    def _record_permanent(state, agent, task_id, task, start_iso, t_start, attempt, e):
        t_end = state.elapsed_ms()
        state.add_trace(task_id=task_id, agent=agent.name, task=task, start=start_iso, end=now_iso(),
                        t_start_ms=t_start, t_end_ms=t_end, duration_ms=round(t_end - t_start, 2),
                        status="FAILED", tools=list(agent.tools_used), attempt=attempt + 1, retries=attempt,
                        error=f"{type(e).__name__}: {e}", output_status="permanent failure (not retried)")
        state.add_error(agent.name, type(e).__name__, str(e), recoverable=False, task_id=task_id)
        agent.send("Supervisor Agent", task, f"task {task_id}", f"Permanent failure: {e}", "FAILED")

    # -------------------------------------------------------------- task runner
    def _make_task_runner(self, state, registry, injector):
        handlers = {
            "search": lambda t: (SearchAgent(state, registry, t["source"]), lambda a: a.run()),
            "synchronize": lambda t: (SupervisorAgent(state, registry), lambda a: a.synchronize()),
            "filter": lambda t: (FilterAgent(state, registry), lambda a: a.run()),
            "validate_checkpoint": lambda t: (ValidatorAgent(state, registry), lambda a: a.checkpoint_filter()),
            "compare": lambda t: (ComparisonAgent(state, registry), lambda a: a.run()),
            "rank": lambda t: (RankingAgent(state, registry), lambda a: a.run()),
            "validate": lambda t: (ValidatorAgent(state, registry), lambda a: a.validate_final()),
            "supervise": lambda t: (SupervisorAgent(state, registry), lambda a: a.supervise()),
        }

        def run_task(task: dict) -> None:
            agent, fn = handlers[task["type"]](task)
            state.set_task_status(task["task_id"], "RUNNING")
            try:
                self._execute(state, injector, agent, task["task_id"], task["description"], fn)
                state.set_task_status(task["task_id"], "SUCCESS")
            except AgentSystemError:
                state.set_task_status(task["task_id"], "FAILED")
        return run_task

    @staticmethod
    def _ready(task: dict, task_status: dict) -> bool:
        statuses = [task_status.get(d) for d in task["depends_on"]]
        if task.get("always_run"):
            return True
        if task.get("allow_partial"):
            return any(s == "SUCCESS" for s in statuses)
        return all(s == "SUCCESS" for s in statuses)

    # -------------------------------------------------------------------- run
    def run(self, query: str, parent_workflow_id: str | None = None) -> WorkflowState:
        cfg = self.config
        t0 = time.perf_counter()
        state = WorkflowState(query, cfg.mode, parent_workflow_id)
        injector = FailureInjector(cfg.failures)
        registry = build_registry(state, injector, cfg.search_latency, cfg.tool_timeout, self.search_cache)
        state.registry = registry  # exposed for tool discovery views
        state.search_cache = self.search_cache
        state.config = cfg

        try:
            self._execute(state, injector, PlannerAgent(state, registry), "P0", "Decompose query & build plan",
                          lambda a: a.run(query, cfg.requirement_overrides, cfg.excluded_product_ids))
            state.set_task_status("P0", "SUCCESS")
            self._execute(state, injector, ValidatorAgent(state, registry), "CP1", "Checkpoint: validate requirements",
                          lambda a: a.checkpoint_requirements())
            state.set_task_status("CP1", "SUCCESS")
        except AgentSystemError:
            state.set_task_status("P0" if state.read("requirements") is None else "CP1", "FAILED")
            self._supervise_and_finish(state, registry, injector, t0)
            return state

        if cfg.tamper_after_planning:  # simulated compromise for security testing
            state._simulate_direct_tamper("requirements", "max_price", 100000)

        try:
            self._execute(state, injector, RouterAgent(state, registry), "R0", "Route tasks & derive execution levels",
                          lambda a: a.run(cfg.mode))
            state.set_task_status("R0", "SUCCESS")
        except AgentSystemError:
            state.set_task_status("R0", "FAILED")
            self._supervise_and_finish(state, registry, injector, t0)
            return state

        routing = state.read("routing")
        tasks = {t["task_id"]: t for t in state.read("plan")["tasks"]}
        run_task = self._make_task_runner(state, registry, injector)

        for lvl in routing["strategy"]:
            task_status = state.read("task_status")
            runnable = []
            for tid in lvl["tasks"]:
                if self._ready(tasks[tid], task_status):
                    runnable.append(tasks[tid])
                else:
                    state.set_task_status(tid, "SKIPPED")
                    state.add_trace(task_id=tid, agent=routing["assignments"][tid], task=tasks[tid]["description"],
                                    start=now_iso(), end=now_iso(), t_start_ms=state.elapsed_ms(),
                                    t_end_ms=state.elapsed_ms(), duration_ms=0.0, status="SKIPPED", tools=[],
                                    attempt=0, retries=0, error="Upstream dependency failed",
                                    output_status="skipped")
            lt0 = time.perf_counter()
            if lvl["execution"] == "parallel" and len(runnable) > 1:
                with ThreadPoolExecutor(max_workers=len(runnable), thread_name_prefix=f"level{lvl['level']}") as ex:
                    futures = [ex.submit(run_task, t) for t in runnable]
                    wait(futures)  # synchronization barrier
                    for f in futures:
                        f.result()  # surface unexpected runtime defects
            else:
                for t in runnable:
                    run_task(t)
            state.append_metric("levels", {"level": lvl["level"], "tasks": [t["task_id"] for t in runnable],
                                           "execution": lvl["execution"],
                                           "wall_time_s": round(time.perf_counter() - lt0, 4)})

        self._finish_metrics(state, t0)
        return state

    def _supervise_and_finish(self, state, registry, injector, t0):
        try:
            self._execute(state, injector, SupervisorAgent(state, registry), "T10", "Supervise workflow",
                          lambda a: a.supervise())
        except AgentSystemError:
            pass
        self._finish_metrics(state, t0)

    @staticmethod
    def _finish_metrics(state: WorkflowState, t0: float) -> None:
        m = state.read("metrics")
        levels = m.get("levels", [])
        search_time = levels[0]["wall_time_s"] if levels else 0.0
        agents = state.agents_seen()
        cost = {
            "agent_calls": m["agent_executions"] * COST_WEIGHTS["agent_call"],
            "tool_calls": m["tool_calls"] * COST_WEIGHTS["tool_call"],
            "retries": m["retries"] * COST_WEIGHTS["retry"],
            "processing_ops": round(m["processing_ops"] * COST_WEIGHTS["processing_op"], 2),
        }
        state.set_metric("total_time_s", round(time.perf_counter() - t0, 4))
        state.set_metric("search_stage_time_s", search_time)
        state.set_metric("agents_executed", agents)
        state.set_metric("num_agents_executed", len(agents))
        state.set_metric("cost_breakdown", cost)
        state.set_metric("cost_units", round(sum(cost.values()), 2))
        log_event(state.workflow_id, "Runtime", "WORKFLOW_FINISHED", status=state.status,
                  total_time_s=round(time.perf_counter() - t0, 4))


# ================================================================ entry points
def run_pipeline(query: str, config: PipelineConfig | None = None, search_cache: dict | None = None,
                 parent_workflow_id: str | None = None) -> WorkflowState:
    return Orchestrator(config, search_cache).run(query, parent_workflow_id)


_PID_RE = re.compile(r"^[A-Z]\d{3}$")


def apply_human_decision(state: WorkflowState, decision: str, reviewer: str = "Reviewer", comment: str = "",
                         excluded_product_ids: list | None = None, requirement_overrides: dict | None = None,
                         config: PipelineConfig | None = None) -> WorkflowState:
    """Human-in-the-loop gate. Returns the same state (approve/reject) or a new re-analysis workflow."""
    decision = (decision or "").strip().lower()
    if decision not in ("approve", "reject", "reanalyze"):
        raise InvalidInputError("Decision must be approve, reject or reanalyze")
    reviewer = re.sub(r"[^\w .@-]", "", reviewer or "").strip()[:60] or "Reviewer"
    comment = re.sub(r"<[^>]*>", "", comment or "")[:500]
    excluded = sorted(set(excluded_product_ids or []))
    if any(not _PID_RE.match(p) for p in excluded):
        raise InvalidInputError("Excluded product ids must look like L001 / P001 / T001")
    status = state.status
    if state.read("human_approval") is not None:
        raise InvalidInputError("A human decision has already been recorded for this workflow")
    if status in ("RUNNING",):
        raise InvalidInputError("Workflow is still running")
    if decision == "approve" and status != "AWAITING_HUMAN_APPROVAL":
        raise InvalidInputError(f"Cannot approve a workflow in status {status}")
    if decision == "reanalyze" and status == "BLOCKED_SECURITY":
        raise InvalidInputError("Security-blocked workflows cannot be re-analysed; start a new run")

    record = {"decision": decision.upper(), "reviewer": reviewer, "comment": comment, "timestamp": now_iso(),
              "excluded_product_ids": excluded, "requirement_overrides": requirement_overrides or {}}
    state.write("Human Reviewer", "human_approval", record)
    state.add_message("Human Reviewer", "Supervisor Agent", "Human decision", f"status={status}",
                      f"{record['decision']}" + (f": {comment}" if comment else ""))
    SupervisorAgent(state, None).finalize(record)

    if decision == "reanalyze":
        prev_req = state.read("requirements") or {}
        base_cfg = config or getattr(state, "config", None) or PipelineConfig()
        merged_overrides = {**(base_cfg.requirement_overrides or {}), **(requirement_overrides or {})}
        cfg = replace(base_cfg, failures={}, tamper_after_planning=False,
                      requirement_overrides=merged_overrides or None,
                      excluded_product_ids=sorted(set(prev_req.get("excluded_product_ids", [])) | set(excluded)))
        return run_pipeline(state.read("user_query"), cfg, getattr(state, "search_cache", None), state.workflow_id)
    return state
