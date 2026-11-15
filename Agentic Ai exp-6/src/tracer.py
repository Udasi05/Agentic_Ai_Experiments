"""JSONL Tracer — writes execution traces to logs/mcp_traces.jsonl."""

import json
import time
import uuid
from pathlib import Path
from src.config import TRACE_FILE, LOG_DIR


def infer_server(tool: str) -> str:
    """Infer server name from tool name."""
    if tool in ("analyze_python", "scan_secrets", "search_code", "run_tests"):
        return "review"
    if tool.startswith("git_"):
        return "git"
    return "filesystem"


class Tracer:
    """Writes structured JSONL trace entries for every tool call attempt."""

    def __init__(self, trace_file: Path = None):
        self.trace_file = trace_file or TRACE_FILE
        self.trace_id = uuid.uuid4().hex[:8].upper()
        self.entries = []

        # Ensure logs directory exists
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    def log(self, task_id: str, tool: str, args: dict = None,
            status: str = "OK", duration_ms: float = 0.0,
            error: str = "", error_type: str = None,
            server: str = "", attempt: int = 1):
        """
        Write one trace entry.
        Fields match Fig. 5:
        TASK, SERVER, TOOL, TRY, STATUS, MS, TIME, ERROR
        """
        if not server:
            server = infer_server(tool)

        status_str = "OK" if status in ("OK", "success") else status.upper()

        entry = {
            "trace_id": self.trace_id,
            "task_id": task_id,
            "server": server,
            "tool": tool,
            "args": args or {},
            "attempt": attempt,
            "try": attempt,
            "status": status_str,
            "duration_ms": round(duration_ms, 1),
            "ms": round(duration_ms, 1),
            "time": time.strftime("%H:%M:%S"),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "error": error or "",
            "error_type": error_type or "",
        }
        self.entries.append(entry)

        # Append to JSONL file
        with open(self.trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def get_entries(self) -> list:
        """Return all trace entries for this session."""
        return list(self.entries)

    @staticmethod
    def read_traces(trace_file: Path = None) -> list:
        """Read all traces from the JSONL file."""
        path = trace_file or TRACE_FILE
        if not path.exists():
            return []
        entries = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return entries
