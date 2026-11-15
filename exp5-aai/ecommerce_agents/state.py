"""Shared workflow state with role-based write control and integrity checking."""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import threading
import time
import uuid
from typing import Any

from .errors import StateAccessError, StateIntegrityError
from .observability import log_event, now_iso

SEARCH_AGENTS = frozenset({"Search Agent A", "Search Agent B", "Search Agent C"})

# Field -> agents allowed to write it (least privilege).
WRITE_PERMISSIONS: dict[str, frozenset[str]] = {
    "requirements": frozenset({"Planner Agent"}),
    "security_flags": frozenset({"Planner Agent"}),
    "plan": frozenset({"Planner Agent"}),
    "routing": frozenset({"Router Agent"}),
    "search_results": SEARCH_AGENTS,
    "synchronized_results": frozenset({"Supervisor Agent"}),
    "conflicts": frozenset({"Supervisor Agent"}),
    "filtered_results": frozenset({"Filter Agent"}),
    "rejected_products": frozenset({"Filter Agent"}),
    "comparison": frozenset({"Comparison Agent"}),
    "ranking": frozenset({"Ranking Agent"}),
    "validation": frozenset({"Validator Agent"}),
    "supervisor_decision": frozenset({"Supervisor Agent"}),
    "status": frozenset({"Supervisor Agent"}),
    "human_approval": frozenset({"Human Reviewer"}),
    "final_recommendation": frozenset({"Supervisor Agent"}),
}

# Fields that can only be written once (locked after first write).
WRITE_ONCE_FIELDS = frozenset({"requirements", "plan", "human_approval"})

# Keyed fields: an agent may only write its own key.
_KEY_OWNERSHIP = {"search_results": {"Search Agent A": "A", "Search Agent B": "B", "Search Agent C": "C"}}


def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


class WorkflowState:
    """Thread-safe shared blackboard used by every agent in one workflow."""

    def __init__(self, user_query: str, mode: str = "parallel", parent_workflow_id: str | None = None):
        self._lock = threading.RLock()
        self._t0 = time.perf_counter()
        self.workflow_id = f"WF-{uuid.uuid4().hex[:8].upper()}"
        self._req_hash: str | None = None
        self._step = 0
        self._agents_seen: list[str] = []
        self._data: dict[str, Any] = {
            "workflow_id": self.workflow_id,
            "parent_workflow_id": parent_workflow_id,
            "user_query": user_query,
            "mode": mode,
            "created_at": now_iso(),
            "status": "RUNNING",
            "requirements": None,
            "security_flags": [],
            "plan": None,
            "routing": None,
            "messages": [],
            "search_results": {},
            "synchronized_results": [],
            "conflicts": [],
            "filtered_results": [],
            "rejected_products": [],
            "comparison": None,
            "ranking": [],
            "validation": {},
            "supervisor_decision": None,
            "human_approval": None,
            "final_recommendation": None,
            "errors": [],
            "trace": [],
            "security_events": [],
            "tool_log": [],
            "task_status": {},
            "metrics": {
                "agent_executions": 0,
                "tool_calls": 0,
                "tool_cache_hits": 0,
                "tool_denials": 0,
                "retries": 0,
                "processing_ops": 0,
                "levels": [],
            },
        }
        log_event(self.workflow_id, "Runtime", "WORKFLOW_CREATED", query=user_query, mode=mode,
                  parent_workflow_id=parent_workflow_id)

    # ------------------------------------------------------------------ time
    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000, 2)

    # ------------------------------------------------------------ controlled writes
    def write(self, agent: str, field: str, value: Any, key: str | None = None) -> None:
        with self._lock:
            allowed = WRITE_PERMISSIONS.get(field)
            if allowed is None or agent not in allowed:
                self.record_security_event(agent, "UNAUTHORIZED_STATE_WRITE",
                                           f"{agent} attempted to modify protected field '{field}'")
                raise StateAccessError(f"Access denied: {agent} is not authorized to modify '{field}'")
            if field in WRITE_ONCE_FIELDS and self._data[field] is not None:
                self.record_security_event(agent, "IMMUTABLE_FIELD_MODIFICATION",
                                           f"{agent} attempted to overwrite locked field '{field}'")
                raise StateAccessError(f"Access denied: '{field}' is locked and cannot be modified")
            owner_map = _KEY_OWNERSHIP.get(field)
            if owner_map is not None and owner_map.get(agent) != key:
                self.record_security_event(agent, "UNAUTHORIZED_STATE_WRITE",
                                           f"{agent} attempted to write '{field}[{key}]' owned by another agent")
                raise StateAccessError(f"Access denied: {agent} may only write its own '{field}' entry")
            value = copy.deepcopy(value)
            if key is None:
                self._data[field] = value
            else:
                if not isinstance(self._data[field], dict):
                    raise StateAccessError(f"Field '{field}' does not support keyed writes")
                self._data[field][key] = value
            if field == "requirements":
                self._req_hash = _digest(value)
            log_event(self.workflow_id, agent, "STATE_WRITE", field=field, key=key)

    # ------------------------------------------------------------------ reads
    def read(self, field: str) -> Any:
        with self._lock:
            return copy.deepcopy(self._data[field])

    def get_requirements(self) -> dict:
        """Return requirements after verifying they were not tampered with."""
        with self._lock:
            if self._data["requirements"] is None:
                raise StateIntegrityError("Requirements are not available yet")
            if not self.verify_integrity():
                self.record_security_event("Runtime", "STATE_INTEGRITY_VIOLATION",
                                           "Requirements hash mismatch: shared state modified outside the write API")
                raise StateIntegrityError("Requirements integrity check failed (possible tampering)")
            return copy.deepcopy(self._data["requirements"])

    def verify_integrity(self) -> bool:
        with self._lock:
            if self._req_hash is None:
                return self._data["requirements"] is None
            return _digest(self._data["requirements"]) == self._req_hash

    @property
    def status(self) -> str:
        with self._lock:
            return self._data["status"]

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    # ------------------------------------------------------- append-only channels
    def add_message(self, sender: str, receiver: str, task: str, input_summary: str,
                    output_summary: str, status: str = "SUCCESS") -> None:
        msg = {"ts": now_iso(), "t_ms": self.elapsed_ms(), "sender": sender, "receiver": receiver,
               "task": task, "input": input_summary, "output": output_summary, "status": status}
        with self._lock:
            self._data["messages"].append(msg)
        log_event(self.workflow_id, sender, "MESSAGE", receiver=receiver, task=task, status=status)

    def add_trace(self, **entry) -> None:
        with self._lock:
            self._step += 1
            self._data["trace"].append({"step": self._step, **entry})
        log_event(self.workflow_id, entry.get("agent", "?"), "TRACE",
                  **{k: v for k, v in entry.items() if k != "agent"})

    def add_error(self, agent: str, error_type: str, message: str, recoverable: bool,
                  task_id: str | None = None, severity: str = "ERROR") -> None:
        err = {"ts": now_iso(), "agent": agent, "task_id": task_id, "type": error_type,
               "message": message, "recoverable": recoverable, "severity": severity}
        with self._lock:
            self._data["errors"].append(err)
        log_event(self.workflow_id, agent, "ERROR", level=logging.WARNING, **{k: v for k, v in err.items() if k != "agent"})

    def record_security_event(self, agent: str, event_type: str, detail: str) -> None:
        ev = {"ts": now_iso(), "agent": agent, "event": event_type, "detail": detail}
        with self._lock:
            self._data["security_events"].append(ev)
        log_event(self.workflow_id, agent, "SECURITY_EVENT", level=logging.WARNING, type=event_type, detail=detail)

    def record_tool_call(self, entry: dict) -> None:
        with self._lock:
            self._data["tool_log"].append({"ts": now_iso(), **entry})

    # ---------------------------------------------------------------- metrics
    def incr(self, metric: str, n: int | float = 1) -> None:
        with self._lock:
            self._data["metrics"][metric] = self._data["metrics"].get(metric, 0) + n

    def set_metric(self, metric: str, value: Any) -> None:
        with self._lock:
            self._data["metrics"][metric] = value

    def append_metric(self, metric: str, value: Any) -> None:
        with self._lock:
            self._data["metrics"].setdefault(metric, []).append(value)

    def mark_agent(self, agent: str) -> None:
        with self._lock:
            if agent not in self._agents_seen:
                self._agents_seen.append(agent)

    def agents_seen(self) -> list[str]:
        with self._lock:
            return list(self._agents_seen)

    # ------------------------------------------------------------- runtime only
    def set_task_status(self, task_id: str, status: str) -> None:
        """Used by the orchestration runtime (not by agents) to track task progress."""
        with self._lock:
            self._data["task_status"][task_id] = status

    def _simulate_direct_tamper(self, field: str, key: str, value: Any) -> None:
        """TEST ONLY: bypasses the write API to simulate a compromised component
        modifying shared memory directly. Integrity checks must detect this."""
        with self._lock:
            self._data[field][key] = value
        log_event(self.workflow_id, "Attacker (simulated)", "DIRECT_STATE_TAMPER", field=field, key=key, value=value)
