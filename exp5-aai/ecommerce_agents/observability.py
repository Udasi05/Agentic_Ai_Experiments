"""Structured JSON-lines logging for workflow events."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "workflow.log"
_LOGGER_NAME = "ecommerce_agents"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def get_logger() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:  # guard against duplicate handlers (e.g. Streamlit reruns)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def log_event(workflow_id: str, agent: str, event: str, level: int = logging.INFO, **fields) -> dict:
    record = {"ts": now_iso(), "workflow_id": workflow_id, "agent": agent, "event": event, **fields}
    get_logger().log(level, json.dumps(record, default=str, ensure_ascii=False))
    return record
