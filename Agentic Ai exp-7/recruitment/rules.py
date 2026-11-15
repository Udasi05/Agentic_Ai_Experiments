"""Load and validate the scoring rules (rules.json)."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .config import SCORE_FIELDS
from .errors import WorkflowError


def _num(value: Any, what: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise WorkflowError(f"{what} must be numeric")
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise WorkflowError(f"{what} must be numeric") from None
    if not d.is_finite():
        raise WorkflowError(f"{what} must be numeric")
    return d


def validate_rules(rules: Any) -> dict[str, Any]:
    """Validate a rules dict; returns it unchanged or raises ``WorkflowError``.

    Requirements: non-empty ``rule_version``; ``criteria`` maps known score fields to
    non-negative numeric weights summing to 100; ``thresholds.shortlist_review`` and
    ``thresholds.manual_review`` numeric, within 0..100, shortlist > manual;
    optional ``target_role`` must be a string.
    """
    if not isinstance(rules, dict):
        raise WorkflowError("Rules must be a JSON object")
    version = rules.get("rule_version")
    if not isinstance(version, str) or not version.strip():
        raise WorkflowError("Rules missing rule_version")
    criteria = rules.get("criteria")
    if not isinstance(criteria, dict) or not criteria:
        raise WorkflowError("Rules missing criteria")
    total = Decimal(0)
    for key, weight in criteria.items():
        if key not in SCORE_FIELDS:
            raise WorkflowError(f"Unknown criterion: {key}")
        w = _num(weight, f"Weight for {key}")
        if w < 0:
            raise WorkflowError(f"Weight for {key} must be non-negative")
        total += w
    if total != 100:
        raise WorkflowError(f"Criteria weights must sum to 100 (got {total})")
    thresholds = rules.get("thresholds")
    if not isinstance(thresholds, dict):
        raise WorkflowError("Rules missing thresholds")
    if "shortlist_review" not in thresholds or "manual_review" not in thresholds:
        raise WorkflowError("Thresholds must define shortlist_review and manual_review")
    sl = _num(thresholds["shortlist_review"], "thresholds.shortlist_review")
    mr = _num(thresholds["manual_review"], "thresholds.manual_review")
    for name, v in (("shortlist_review", sl), ("manual_review", mr)):
        if v < 0 or v > 100:
            raise WorkflowError(f"thresholds.{name} must be between 0 and 100")
    if not sl > mr:
        raise WorkflowError("thresholds.shortlist_review must be greater than thresholds.manual_review")
    if "target_role" in rules and rules["target_role"] is not None and not isinstance(rules["target_role"], str):
        raise WorkflowError("target_role must be a string")
    return rules


def load_rules(path: str | Path) -> dict[str, Any]:
    """Read and validate a rules JSON file. Raises ``WorkflowError`` on any problem."""
    p = Path(path)
    if not p.is_file():
        raise WorkflowError(f"Rules file not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"Rules file is not valid JSON: {exc}") from exc
    return validate_rules(data)
