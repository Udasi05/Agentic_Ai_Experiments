"""Basic MCP-style tool layer: registration, discovery, authorization, validated execution.

NOTE: This is intentionally a simplified, in-process interface that mirrors MCP
concepts (tool descriptors with input schemas, list/call semantics). It is NOT an
implementation of the full MCP protocol (no JSON-RPC transport, sessions, etc.).
"""
from __future__ import annotations

import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from typing import Any, Callable

from . import data, logic
from .errors import (AccessDeniedError, PermanentToolError, ToolTimeoutError, ToolValidationError,
                     TransientToolError)
from .observability import log_event
from .state import SEARCH_AGENTS, WorkflowState

_TYPES = {"str": str, "dict": dict, "list": list, "float": (int, float), "int": int, "bool": bool}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    capability: str
    input_schema: dict  # {"param": {"type": "str", "required": True, "description": "..."}}
    handler: Callable[..., Any]
    allowed_agents: frozenset
    timeout_s: float | None = None
    cacheable: bool = False

    def descriptor(self) -> dict:
        return {"name": self.name, "description": self.description, "capability": self.capability,
                "inputSchema": self.input_schema, "allowed_agents": sorted(self.allowed_agents),
                "timeout_s": self.timeout_s, "cacheable": self.cacheable}


class FailureInjector:
    """Deterministic fault injection for failure testing.

    plan maps a key ("search:A", "agent:Comparison Agent") to a list of failure kinds
    consumed one per attempt: "transient", "timeout", or "permanent" (never consumed).
    """

    def __init__(self, plan: dict | None = None):
        self._plan = {k: list(v) for k, v in (plan or {}).items()}
        self._lock = threading.Lock()

    def next_failure(self, key: str) -> str | None:
        with self._lock:
            queue = self._plan.get(key)
            if not queue:
                return None
            if queue[0] == "permanent":
                return "permanent"
            return queue.pop(0)


class ToolRegistry:
    """Per-workflow registry. Every call is authorized, validated, logged and counted."""

    def __init__(self, state: WorkflowState, search_cache: dict | None = None):
        self._tools: dict[str, Tool] = {}
        self._state = state
        self._lock = threading.Lock()
        self.cache: dict = search_cache if search_cache is not None else {}

    # ---------------------------------------------------------- registration
    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    # ------------------------------------------------------------- discovery
    def list_tools(self) -> list[dict]:
        return [t.descriptor() for t in self._tools.values()]

    def discover(self, agent: str) -> list[dict]:
        """Tools visible to an agent (least privilege: only authorized tools)."""
        return [t.descriptor() for t in self._tools.values() if agent in t.allowed_agents]

    def permission_matrix(self, agents: list[str]) -> list[dict]:
        return [{"Agent": a, **{t.name: ("✅" if a in t.allowed_agents else "—") for t in self._tools.values()}}
                for a in agents]

    # ------------------------------------------------------------- execution
    def _validate_args(self, tool: Tool, args: dict) -> None:
        unknown = set(args) - set(tool.input_schema)
        if unknown:
            raise ToolValidationError(f"Tool '{tool.name}' received unknown argument(s): {sorted(unknown)}")
        for name, spec in tool.input_schema.items():
            if name not in args:
                if spec.get("required", True):
                    raise ToolValidationError(f"Tool '{tool.name}' missing required argument '{name}'")
                continue
            expected = _TYPES[spec["type"]]
            if isinstance(args[name], bool) and spec["type"] != "bool" or not isinstance(args[name], expected):
                raise ToolValidationError(f"Tool '{tool.name}' argument '{name}' must be of type {spec['type']}")

    def _invoke(self, tool: Tool, args: dict) -> Any:
        if tool.timeout_s is None:
            return tool.handler(**args)
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"tool-{tool.name}")
        try:
            future = executor.submit(tool.handler, **args)
            try:
                return future.result(timeout=tool.timeout_s)
            except FuturesTimeout:
                raise ToolTimeoutError(f"Tool '{tool.name}' exceeded its {tool.timeout_s}s timeout") from None
        finally:
            executor.shutdown(wait=False)

    def call(self, agent: str, tool_name: str, **args) -> Any:
        state = self._state
        tool = self._tools.get(tool_name)
        base = {"agent": agent, "tool": tool_name, "args": sorted(args)}
        if tool is None:
            state.record_security_event(agent, "UNKNOWN_TOOL_REQUEST", f"{agent} requested unregistered tool '{tool_name}'")
            state.record_tool_call({**base, "status": "REJECTED", "error": "unknown tool"})
            raise ToolValidationError(f"Tool '{tool_name}' is not registered")
        if agent not in tool.allowed_agents:
            state.incr("tool_denials")
            state.record_security_event(agent, "UNAUTHORIZED_TOOL_ACCESS", f"{agent} was denied access to '{tool_name}'")
            state.record_tool_call({**base, "status": "DENIED", "error": "not authorized"})
            raise AccessDeniedError(f"Access denied: {agent} is not authorized to use '{tool_name}'")
        try:
            self._validate_args(tool, args)
        except ToolValidationError as e:
            state.record_tool_call({**base, "status": "REJECTED", "error": str(e)})
            raise

        cache_key = None
        if tool.cacheable:
            cache_key = (tool_name, tuple(sorted((k, repr(v)) for k, v in args.items())))
            with self._lock:
                if cache_key in self.cache:
                    state.incr("tool_cache_hits")
                    state.record_tool_call({**base, "status": "CACHE_HIT", "duration_ms": 0.0})
                    log_event(state.workflow_id, agent, "TOOL_CACHE_HIT", tool=tool_name)
                    return copy.deepcopy(self.cache[cache_key])

        state.incr("tool_calls")
        t0 = time.perf_counter()
        try:
            result = self._invoke(tool, copy.deepcopy(args))
        except Exception as e:
            dur = round((time.perf_counter() - t0) * 1000, 2)
            state.record_tool_call({**base, "status": "FAILED", "duration_ms": dur, "error": f"{type(e).__name__}: {e}"})
            log_event(state.workflow_id, agent, "TOOL_FAILED", tool=tool_name, error=str(e))
            raise
        dur = round((time.perf_counter() - t0) * 1000, 2)
        state.record_tool_call({**base, "status": "SUCCESS", "duration_ms": dur})
        log_event(state.workflow_id, agent, "TOOL_CALL", tool=tool_name, duration_ms=dur)
        if cache_key is not None:
            with self._lock:
                self.cache[cache_key] = copy.deepcopy(result)
        return result


# ===================================================================== tools
def _make_search_handler(injector: FailureInjector, latency: float, timeout_s: float):
    def product_search(source: str, category: str) -> list:
        if source not in data.SOURCES:
            raise ToolValidationError(f"Unknown catalog source '{source}'")
        if category not in data.SUPPORTED_CATEGORIES:
            raise ToolValidationError(f"Unsupported category '{category}'")
        kind = injector.next_failure(f"search:{source}")
        if kind == "permanent":
            raise PermanentToolError(f"Catalog source {source} ({data.SOURCES[source]['name']}) is permanently unavailable")
        if kind == "timeout":
            time.sleep(timeout_s + 0.25)  # exceed the timeout; result is discarded
            return []
        time.sleep(latency)  # simulated network / API latency
        if kind == "transient":
            raise TransientToolError(f"Catalog source {source} returned HTTP 503 (transient)")
        return [p for p in data.get_source_catalog(source) if p["category"] == category]
    return product_search


def build_registry(state: WorkflowState, injector: FailureInjector, search_latency: float,
                   tool_timeout: float, search_cache: dict | None = None) -> ToolRegistry:
    reg = ToolRegistry(state, search_cache)
    req_schema = {"type": "dict", "required": True, "description": "Validated structured requirements"}
    prod_schema = {"type": "list", "required": True, "description": "Product records"}
    reg.register(Tool("query_parser", "Parse a natural-language query into structured requirements with injection screening.",
                      "planning", {"query": {"type": "str", "required": True, "description": "Raw user query"}},
                      logic.parse_query, frozenset({"Planner Agent"})))
    reg.register(Tool("product_search", "Search one catalog source for candidate products of a category.",
                      "search", {"source": {"type": "str", "required": True, "description": "Catalog source id (A/B/C)"},
                                 "category": {"type": "str", "required": True, "description": "Product category"}},
                      _make_search_handler(injector, search_latency, tool_timeout), SEARCH_AGENTS,
                      timeout_s=tool_timeout, cacheable=True))
    reg.register(Tool("synchronize_results", "Merge parallel search outputs and resolve data conflicts.",
                      "workflow-control", {"results_by_source": {"type": "dict", "required": True, "description": "source -> products"}},
                      logic.synchronize_results, frozenset({"Supervisor Agent"})))
    reg.register(Tool("filter_products", "Apply hard constraints (budget, RAM, storage, rating, stock, brand).",
                      "filter", {"products": prod_schema, "requirements": req_schema},
                      logic.filter_products, frozenset({"Filter Agent"})))
    reg.register(Tool("compare_products", "Compare qualifying products on price, RAM, storage, rating and specs.",
                      "comparison", {"products": prod_schema, "requirements": req_schema},
                      logic.compare_products, frozenset({"Comparison Agent"})))
    reg.register(Tool("score_products", "Requirement-aware transparent scoring and sorting.",
                      "ranking", {"products": prod_schema, "requirements": req_schema},
                      logic.score_products, frozenset({"Ranking Agent"})))
    reg.register(Tool("validate_requirements", "Checkpoint: validate decomposed requirements.",
                      "validation", {"requirements": req_schema},
                      logic.validate_requirements, frozenset({"Validator Agent"})))
    reg.register(Tool("validate_filtered", "Checkpoint: verify every filtered product satisfies constraints.",
                      "validation", {"filtered": prod_schema, "requirements": req_schema},
                      logic.validate_filtered, frozenset({"Validator Agent"})))
    reg.register(Tool("validate_recommendation", "Final check: compliance, completeness, ranking correctness, integrity.",
                      "validation", {"ranking": prod_schema, "filtered": prod_schema, "requirements": req_schema,
                                     "integrity_ok": {"type": "bool", "required": True, "description": "State integrity flag"}},
                      logic.validate_recommendation, frozenset({"Validator Agent"})))
    return reg
