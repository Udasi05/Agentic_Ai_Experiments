"""CSV ingestion: load, validate, normalize, de-duplicate and quarantine candidate records."""

from __future__ import annotations

import csv
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .config import ALL_COLUMNS, REQUIRED_COLUMNS, SCORE_FIELDS
from .errors import WorkflowError

REJECTED_FIELDS = ("row", "candidate_id", "reason")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def load_candidates(path: str | Path) -> list[dict[str, Any]]:
    """Read the candidate CSV strictly.

    Returns a list of raw row dicts (all values ``str``; missing cells ``""``) with an extra
    ``"row"`` key holding the 1-based file line number (header = line 1, first data row = 2).

    Raises ``WorkflowError`` if the file is missing/unreadable, empty, malformed
    (``csv.Error`` with ``strict=True``) or the header lacks a required column.
    """
    p = Path(path)
    if not p.is_file():
        raise WorkflowError(f"Candidate file not found: {p}")
    rows: list[dict[str, Any]] = []
    try:
        with p.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh, strict=True)
            try:
                header = next(reader)
            except StopIteration:
                raise WorkflowError("Candidate file is empty (no header)") from None
            header = [h.strip() for h in header]
            missing = [c for c in REQUIRED_COLUMNS if c not in header]
            if missing:
                raise WorkflowError("Invalid header - missing required column(s): " + ", ".join(missing))
            for values in reader:
                line_no = reader.line_num
                if not values or all(not v.strip() for v in values):
                    continue  # skip blank lines
                rec: dict[str, Any] = {}
                for i, col in enumerate(header):
                    rec[col] = values[i] if i < len(values) else ""
                for col in ALL_COLUMNS:
                    rec.setdefault(col, "")
                rec["row"] = line_no
                rows.append(rec)
    except csv.Error as exc:
        raise WorkflowError(f"Malformed CSV: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise WorkflowError(f"Candidate file is not valid UTF-8: {exc}") from exc
    return rows


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _to_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not d.is_finite():
        return None
    return d


def validate_candidate(candidate: dict[str, Any]) -> tuple[bool, str]:
    """Pure validation of one raw record. Returns ``(True, "")`` or ``(False, reason)``.

    Check order: required fields (column order) -> numeric parse -> range 0..100 -> email format.
    Reasons: ``"Missing field: <col>"``, ``"Invalid numeric value: <col>"``,
    ``"<col> must be between 0 and 100"``, ``"Invalid email format"``.
    (Duplicates are detected by :func:`ingest`, not here.)
    """
    for col in REQUIRED_COLUMNS:
        if _is_blank(candidate.get(col)):
            return False, f"Missing field: {col}"
    for col in SCORE_FIELDS:
        if _to_decimal(candidate.get(col)) is None:
            return False, f"Invalid numeric value: {col}"
    for col in SCORE_FIELDS:
        d = _to_decimal(candidate.get(col))
        if d < 0 or d > 100:
            return False, f"{col} must be between 0 and 100"
    if not _EMAIL_RE.match(str(candidate.get("email")).strip()):
        return False, "Invalid email format"
    return True, ""


def normalize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Normalize a *valid* raw record.

    candidate_id upper-cased/stripped, name & role whitespace-collapsed, email lower-cased,
    score fields -> ``Decimal``, cover_note stripped (kept but never used for scoring).
    """
    def collapse(s: Any) -> str:
        return " ".join(str(s or "").split())

    out = {
        "row": candidate.get("row"),
        "candidate_id": str(candidate["candidate_id"]).strip().upper(),
        "name": collapse(candidate["name"]),
        "email": str(candidate["email"]).strip().lower(),
        "role": collapse(candidate["role"]),
        "cover_note": str(candidate.get("cover_note") or "").strip(),
    }
    for col in SCORE_FIELDS:
        out[col] = _to_decimal(candidate[col])
    return out


def ingest(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate, normalize and de-duplicate raw rows.

    Returns ``(valid, rejected)`` where ``valid`` are normalized candidate dicts (file order)
    and ``rejected`` are ``{"row", "candidate_id", "reason"}`` dicts. A duplicate is a valid
    record whose candidate_id was already accepted:
    ``"Duplicate candidate_id (first seen at row N)"``.
    """
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    first_seen: dict[str, int] = {}
    for raw in rows:
        row_no = raw.get("row")
        cid = str(raw.get("candidate_id") or "").strip().upper()
        ok, reason = validate_candidate(raw)
        if not ok:
            rejected.append({"row": row_no, "candidate_id": cid, "reason": reason})
            continue
        if cid in first_seen:
            rejected.append({
                "row": row_no,
                "candidate_id": cid,
                "reason": f"Duplicate candidate_id (first seen at row {first_seen[cid]})",
            })
            continue
        first_seen[cid] = row_no
        valid.append(normalize_candidate(raw))
    return valid, rejected


def count_duplicates(rejected: list[dict[str, Any]]) -> int:
    return sum(1 for r in rejected if str(r.get("reason", "")).startswith("Duplicate candidate_id"))


def write_rejected(rejected: list[dict[str, Any]], path: str | Path) -> Path:
    """Write ``rejected_records.csv`` (columns: row, candidate_id, reason). Overwrites."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=REJECTED_FIELDS)
        w.writeheader()
        for r in rejected:
            w.writerow({k: r.get(k, "") for k in REJECTED_FIELDS})
    return p
