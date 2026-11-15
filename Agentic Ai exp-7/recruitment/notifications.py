"""Simulated, idempotent notification dispatcher (appends to sent_notifications.csv)."""

from __future__ import annotations

import csv
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .errors import DeliveryError

SENT_FIELDS = ("notification_id", "candidate_id", "status", "subject", "message", "reviewer_id", "attempts", "sent_at")


def load_sent(path: str | Path) -> list[dict[str, str]]:
    p = Path(path)
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class NotificationDispatcher:
    """Simulated delivery channel.

    * ``fail_ids``: candidate ids whose every attempt fails (permanent failure).
    * ``transient_failures``: ``{candidate_id: n}`` -> the first ``n`` attempts fail.
    * ``simulate_failure``: every attempt fails (UI toggle).

    :meth:`send` appends one row to ``sent_notifications.csv`` on success and raises
    ``DeliveryError`` on a simulated failure. :meth:`already_sent` enables idempotency.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        fail_ids: Iterable[str] = (),
        transient_failures: dict[str, int] | None = None,
        simulate_failure: bool = False,
    ):
        self.path = Path(path)
        self.fail_ids = {str(x).upper() for x in fail_ids}
        self.transient_failures = {str(k).upper(): int(v) for k, v in (transient_failures or {}).items()}
        self.simulate_failure = simulate_failure

    def sent_ids(self) -> set[str]:
        return {r["candidate_id"] for r in load_sent(self.path)}

    def already_sent(self, candidate_id: str) -> bool:
        return candidate_id in self.sent_ids()

    def _should_fail(self, candidate_id: str, attempt: int) -> bool:
        cid = candidate_id.upper()
        return self.simulate_failure or cid in self.fail_ids or attempt <= self.transient_failures.get(cid, 0)

    def send(
        self,
        candidate_id: str,
        status: str,
        subject: str,
        message: str,
        reviewer_id: str,
        attempt: int = 1,
    ) -> dict[str, Any]:
        if self._should_fail(candidate_id, attempt):
            raise DeliveryError(f"Simulated delivery failure for {candidate_id} (attempt {attempt})")
        row = {
            "notification_id": uuid.uuid4().hex[:12],
            "candidate_id": candidate_id,
            "status": status,
            "subject": subject,
            "message": message,
            "reviewer_id": reviewer_id,
            "attempts": attempt,
            "sent_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not self.path.exists() or self.path.stat().st_size == 0
        with self.path.open("a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=SENT_FIELDS)
            if new_file:
                w.writeheader()
            w.writerow(row)
        return row
