"""Threshold routing plus role-mismatch override."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .config import MANUAL_REVIEW, NOT_SHORTLISTED_REVIEW, SHORTLIST_REVIEW


def route_candidate(score: Any, rules: dict[str, Any]) -> str:
    """Pure threshold routing: >= shortlist -> SHORTLIST_REVIEW, >= manual -> MANUAL_REVIEW,
    else NOT_SHORTLISTED_REVIEW (75 -> SHORTLIST, 74.99 -> MANUAL, 50 -> MANUAL, 49.99 -> NOT)."""
    s = Decimal(str(score))
    t = rules["thresholds"]
    if s >= Decimal(str(t["shortlist_review"])):
        return SHORTLIST_REVIEW
    if s >= Decimal(str(t["manual_review"])):
        return MANUAL_REVIEW
    return NOT_SHORTLISTED_REVIEW


def _norm_role(role: Any) -> str:
    return " ".join(str(role or "").split()).casefold()


def is_role_mismatch(candidate: dict[str, Any], rules: dict[str, Any]) -> bool:
    target = rules.get("target_role")
    if not target:
        return False
    return _norm_role(candidate.get("role")) != _norm_role(target)


def route_decision(candidate: dict[str, Any], score: Any, rules: dict[str, Any]) -> dict[str, Any]:
    """Returns ``{"status": str, "reason": str, "role_mismatch": bool}``."""
    if is_role_mismatch(candidate, rules):
        return {
            "status": MANUAL_REVIEW,
            "reason": f"Role mismatch: applied for '{candidate.get('role')}', target role is '{rules.get('target_role')}'",
            "role_mismatch": True,
        }
    status = route_candidate(score, rules)
    t = rules["thresholds"]
    reasons = {
        SHORTLIST_REVIEW: f"Score >= {t['shortlist_review']}",
        MANUAL_REVIEW: f"{t['manual_review']} <= score < {t['shortlist_review']}",
        NOT_SHORTLISTED_REVIEW: f"Score < {t['manual_review']}",
    }
    return {"status": status, "reason": reasons[status], "role_mismatch": False}


def route(candidate: dict[str, Any], score: Any, rules: dict[str, Any]) -> str:
    """Final proposed status (role mismatch -> MANUAL_REVIEW, otherwise thresholds)."""
    return route_decision(candidate, score, rules)["status"]
