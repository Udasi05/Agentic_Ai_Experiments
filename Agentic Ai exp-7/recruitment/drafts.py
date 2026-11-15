"""Status-specific notification drafts (never final, never show scores) + optional Gemini polish."""

from __future__ import annotations

import os
import re
from typing import Any

from .config import (
    GEMINI_ENV_VAR,
    GEMINI_MODEL,
    GEMINI_MODELS,
    MANUAL_REVIEW,
    NOT_SHORTLISTED_REVIEW,
    REVIEW_INFO_REQUESTED,
    REVIEW_ON_HOLD,
    SHORTLIST_REVIEW,
)

DRAFT_LABEL = "DRAFT"
DRAFT_HEADER = "DRAFT - pending human review"

_TEMPLATES: dict[str, tuple[str, str]] = {
    SHORTLIST_REVIEW: (
        "Your application is moving to the next review stage",
        "Thank you for applying for the {role} position. Your application has been "
        "identified as a strong match in our initial screening and is moving to the next "
        "review stage, where a member of our recruitment team will look at it in detail.\n\n"
        "We will be in touch soon about next steps.",
    ),
    MANUAL_REVIEW: (
        "Your application is under review",
        "Thank you for applying for the {role} position. Your application has been passed "
        "to our recruitment team for a detailed review.\n\n"
        "We will contact you once the review is complete.",
    ),
    NOT_SHORTLISTED_REVIEW: (
        "Update on your application",
        "Thank you for your interest in the {role} position. Your application is still "
        "being reviewed by our recruitment team and no decision has been made yet.\n\n"
        "We will contact you with an update once the review is complete.",
    ),
    REVIEW_ON_HOLD: (
        "Your application is on hold",
        "Thank you for applying for the {role} position. Your application is currently on "
        "hold while our recruitment team completes its review.\n\n"
        "We will contact you as soon as there is an update.",
    ),
    REVIEW_INFO_REQUESTED: (
        "Additional information requested",
        "Thank you for applying for the {role} position. To continue reviewing your "
        "application, our recruitment team would like some additional information.\n\n"
        "A member of the team will contact you shortly with details.",
    ),
}

FORBIDDEN_PHRASES = (
    "rejected", "reject", "rejection", "unsuccessful", "not selected", "not been selected",
    "regret", "regretfully", "unfortunately", "hired", "offer", "offered", "congratulations",
    "declined", "not shortlisted", "final decision", "score", "scored", "points",
)
_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in FORBIDDEN_PHRASES) + r")\b", re.IGNORECASE)


def reference_line(candidate_id: str) -> str:
    return f"Application reference: {candidate_id}"


def generate_draft(candidate: dict[str, Any], status: str) -> dict[str, Any]:
    """Build a template draft for ``status`` (any routing status, or ON_HOLD / INFO_REQUESTED).

    Returns ``{"candidate_id", "status", "label": "DRAFT", "subject", "message", "source": "template"}``.
    ``subject`` starts with ``"[DRAFT] "``; ``message`` starts with ``"DRAFT - pending human review"``
    and contains ``"Application reference: <id>"``. No scores, no final-decision language.
    """
    if status not in _TEMPLATES:
        raise ValueError(f"Unknown status for draft: {status}")
    subject, body = _TEMPLATES[status]
    cid = candidate.get("candidate_id", "")
    name = candidate.get("name") or "Candidate"
    role = candidate.get("role") or "advertised"
    message = (
        f"{DRAFT_HEADER}\n\nDear {name},\n\n{body.format(role=role)}\n\n"
        f"{reference_line(cid)}\n\nKind regards,\nRecruitment Team"
    )
    return {
        "candidate_id": cid,
        "status": status,
        "label": DRAFT_LABEL,
        "subject": f"[{DRAFT_LABEL}] {subject}",
        "message": message,
        "source": "template",
    }


def validate_polished(text: str, candidate: dict[str, Any] | str) -> tuple[bool, str]:
    """Output guard for LLM-polished text. Returns ``(True, "")`` or ``(False, reason)``.

    Rejects: empty text; missing ``Application reference: <id>`` line; final-decision /
    score language (see ``FORBIDDEN_PHRASES``); any digit outside the candidate id
    (numbers could disclose a score).
    """
    cid = candidate if isinstance(candidate, str) else str(candidate.get("candidate_id", ""))
    if not text or not text.strip():
        return False, "Empty text"
    if reference_line(cid) not in text:
        return False, "Missing application reference line"
    m = _FORBIDDEN_RE.search(text)
    if m:
        return False, f"Forbidden language: '{m.group(0)}'"
    stripped = re.sub(re.escape(cid), "", text, flags=re.IGNORECASE) if cid else text
    if re.search(r"\d", stripped) or "%" in stripped:
        return False, "Contains numeric value that may disclose a score"
    return True, ""


def _build_prompt(draft: dict[str, Any]) -> str:
    return (
        "Polish the wording of this candidate notification so it is warm, professional and concise. "
        "Rules: keep the first line exactly 'DRAFT - pending human review'; keep the line "
        f"'{reference_line(draft['candidate_id'])}' exactly; do not mention any scores, numbers, "
        "percentages, offers, hiring or rejection; do not imply any final decision. "
        "Return only the message text.\n\n---\n" + draft["message"]
    )


def polish_draft(
    draft: dict[str, Any],
    candidate: dict[str, Any] | None = None,
    *,
    api_key: str | None = None,
    model: str = GEMINI_MODEL,
    client: Any = None,
) -> dict[str, Any]:
    """Optionally polish ``draft["message"]`` with Gemini; never raises.

    Uses ``client`` if given (anything with ``.models.generate_content(model=, contents=)``
    returning an object with ``.text``), else creates ``google.genai.Client(api_key=...)`` from
    ``api_key`` or the ``GEMINI_API_KEY`` env var. Returns a NEW draft dict with extra keys
    ``"polish_status"`` ("POLISHED" | "FALLBACK") and ``"polish_reason"``; on fallback the
    original subject/message are kept and ``source`` stays ``"template"``; on success
    ``source == "gemini"``.
    """
    candidate = candidate or {"candidate_id": draft.get("candidate_id", "")}
    result = dict(draft)

    def fallback(reason: str) -> dict[str, Any]:
        result.update({"message": draft["message"], "source": draft.get("source", "template"),
                       "polish_status": "FALLBACK", "polish_reason": reason})
        return result

    try:
        if client is None:
            key = api_key or os.environ.get(GEMINI_ENV_VAR)
            if not key:
                return fallback(f"{GEMINI_ENV_VAR} not set")
            from google import genai  # local import: optional dependency

            client = genai.Client(api_key=key)

        # Try specified model, fallback to alternative models if 404 NOT_FOUND
        models_to_try = [model] + [m for m in GEMINI_MODELS if m != model]
        response = None
        last_error = None

        for target_model in models_to_try:
            try:
                response = client.models.generate_content(model=target_model, contents=_build_prompt(draft))
                break
            except Exception as e:
                last_error = e
                # Only retry next model if not found / deprecated
                if "404" in str(e) or "NOT_FOUND" in str(e) or "not available" in str(e).lower():
                    continue
                raise

        if response is None:
            if last_error:
                raise last_error
            return fallback("No model response generated")

        text = (getattr(response, "text", None) or "").strip()
        if text and not text.startswith(DRAFT_HEADER):
            text = f"{DRAFT_HEADER}\n\n{text}"
        ok, reason = validate_polished(text, candidate)
        if not ok:
            return fallback(f"Guard rejected polished text: {reason}")
        result.update({"message": text, "source": "gemini", "polish_status": "POLISHED", "polish_reason": ""})
        return result
    except Exception as exc:  # any API / network / import error -> safe fallback
        err_msg = str(exc)
        if len(err_msg) > 120:
            err_msg = err_msg[:120] + "..."
        return fallback(f"Gemini error: {type(exc).__name__} ({err_msg})")
