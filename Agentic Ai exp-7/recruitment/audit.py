"""Append-only audit log. Never records candidate names or emails."""

from __future__ import annotations

import csv
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

AUDIT_FIELDS = ("timestamp", "run_id", "event", "candidate_id", "actor", "role", "status", "rule_version", "details")

# Event names
RUN_STARTED = "RUN_STARTED"
RULES_LOADED = "RULES_LOADED"
RECORDS_LOADED = "RECORDS_LOADED"
RECORD_QUARANTINED = "RECORD_QUARANTINED"
CANDIDATE_SCORED = "CANDIDATE_SCORED"
CANDIDATE_ROUTED = "CANDIDATE_ROUTED"
DRAFT_CREATED = "DRAFT_CREATED"
RUN_COMPLETED = "RUN_COMPLETED"
WORKFLOW_FAILED = "WORKFLOW_FAILED"
ACCESS_DENIED = "ACCESS_DENIED"
REVIEW_REJECTED = "REVIEW_REJECTED"
REVIEW_DECISION = "REVIEW_DECISION"
STATUS_OVERRIDDEN = "STATUS_OVERRIDDEN"
NOTIFICATION_SENT = "NOTIFICATION_SENT"
NOTIFICATION_RETRY = "NOTIFICATION_RETRY"
NOTIFICATION_FAILED = "NOTIFICATION_FAILED"
NOTIFICATION_SKIPPED = "NOTIFICATION_SKIPPED"
DRAFT_POLISHED = "DRAFT_POLISHED"
POLISH_FALLBACK = "POLISH_FALLBACK"

AUDIT_EVENTS = (
    RUN_STARTED, RULES_LOADED, RECORDS_LOADED, RECORD_QUARANTINED, CANDIDATE_SCORED,
    CANDIDATE_ROUTED, DRAFT_CREATED, RUN_COMPLETED, WORKFLOW_FAILED, ACCESS_DENIED,
    REVIEW_REJECTED, REVIEW_DECISION, STATUS_OVERRIDDEN, NOTIFICATION_SENT, NOTIFICATION_RETRY,
    NOTIFICATION_FAILED, NOTIFICATION_SKIPPED, DRAFT_POLISHED, POLISH_FALLBACK,
)

_EMAIL_RE = re.compile(r"[^@\s,;]+@[^@\s,;]+")
REDACTED = "[REDACTED]"


class AuditLogger:
    """Append-only CSV audit logger with fixed columns ``AUDIT_FIELDS``.

    Every value is scrubbed: email-like tokens and any registered sensitive strings
    (candidate names/emails, see :meth:`register_sensitive`) are replaced by ``[REDACTED]``.
    """

    def __init__(self, path: str | Path, run_id: str | None = None):
        self.path = Path(path)
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self._sensitive: set[str] = set()

    def register_sensitive(self, values: Iterable[str]) -> None:
        for v in values:
            v = str(v or "").strip()
            if len(v) >= 3:
                self._sensitive.add(v)

    def _scrub(self, value: Any) -> str:
        s = "" if value is None else str(value)
        s = _EMAIL_RE.sub(REDACTED, s)
        for term in sorted(self._sensitive, key=len, reverse=True):
            if term in s:
                s = s.replace(term, REDACTED)
        return s

    def log(
        self,
        event: str,
        candidate_id: str = "",
        *,
        actor: str = "system",
        role: str = "system",
        status: str = "",
        details: str = "",
        rule_version: str = "",
    ) -> dict[str, str]:
        """Append one row and return it."""
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "run_id": self.run_id,
            "event": event,
            "candidate_id": candidate_id or "",
            "actor": actor,
            "role": role,
            "status": status,
            "rule_version": rule_version,
            "details": details,
        }
        row = {k: self._scrub(v) for k, v in row.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not self.path.exists() or self.path.stat().st_size == 0
        with self.path.open("a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=AUDIT_FIELDS)
            if new_file:
                w.writeheader()
            w.writerow(row)
        return row


from recruitment.config import DEFAULT_OUTPUTS_DIR, get_output_paths

def read_audit_log(path: str | Path | None = None) -> list[dict[str, str]]:
    """Return all audit rows (empty list if the file does not exist). Defaults to default audit log path."""
    if path is None:
        p = get_output_paths(DEFAULT_OUTPUTS_DIR).audit
    else:
        p = Path(path)
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))
