"""Transparent, deterministic Decimal scoring: S = sum(input_i * weight_i / 100)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable

from .config import CRITERION_LABELS

TWO_PLACES = Decimal("0.01")


def _q(d: Decimal) -> Decimal:
    return d.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def score_candidate(candidate: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    """Score one candidate. Only the criteria fields are read (``cover_note`` etc. ignored).

    Returns::

        {"candidate_id": str, "score": Decimal (2dp), "rule_version": str,
         "breakdown": [{"criterion": "skills_score", "label": "Skills", "input": Decimal,
                        "weight": Decimal, "contribution": Decimal (2dp)}, ...]}

    Raises ``ValueError`` if an input is missing / non-numeric / outside 0..100.
    """
    breakdown = []
    total = Decimal(0)
    for criterion, weight in rules["criteria"].items():
        raw = candidate.get(criterion)
        try:
            value = Decimal(str(raw).strip())
        except Exception:
            raise ValueError(f"Invalid numeric value: {criterion}") from None
        if not value.is_finite():
            raise ValueError(f"Invalid numeric value: {criterion}")
        if value < 0 or value > 100:
            raise ValueError(f"{criterion} must be between 0 and 100")
        w = Decimal(str(weight))
        contribution = value * w / Decimal(100)
        total += contribution
        breakdown.append({
            "criterion": criterion,
            "label": CRITERION_LABELS.get(criterion, criterion),
            "input": value,
            "weight": w,
            "contribution": _q(contribution),
        })
    return {
        "candidate_id": candidate.get("candidate_id", ""),
        "score": _q(total),
        "rule_version": rules.get("rule_version", ""),
        "breakdown": breakdown,
    }


def format_score(score: Any) -> str:
    """Human format: at most 2 decimals, at least 1 (82 -> "82.0", 74.5 -> "74.5", 49.99 -> "49.99")."""
    s = f"{_q(Decimal(str(score))):f}".rstrip("0")
    if s.endswith("."):
        s += "0"
    return s


def check_score_consistency(candidates: Iterable[dict[str, Any]], rules: dict[str, Any]) -> tuple[int, int]:
    """Re-score every candidate twice; returns ``(identical_count, total)``.

    If a candidate dict carries a previously stored ``"score"`` it must also match it.
    """
    identical = total = 0
    for c in candidates:
        total += 1
        a = score_candidate(c, rules)["score"]
        b = score_candidate(c, rules)["score"]
        stored = c.get("score")
        if a == b and (stored is None or Decimal(str(stored)) == a):
            identical += 1
    return identical, total
