"""Central configuration: default paths, column names, statuses, roles and actions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_PATH = PROJECT_ROOT / "data" / "candidates.csv"
DEFAULT_RULES_PATH = PROJECT_ROOT / "rules.json"
DEFAULT_OUTPUTS_DIR = PROJECT_ROOT / "outputs"

# --- CSV schema -----------------------------------------------------------
SCORE_FIELDS = ("skills_score", "experience_score", "assessment_score")
REQUIRED_COLUMNS = ("candidate_id", "name", "email", "role") + SCORE_FIELDS
OPTIONAL_COLUMNS = ("cover_note",)
ALL_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

CRITERION_LABELS = {
    "skills_score": "Skills",
    "experience_score": "Experience",
    "assessment_score": "Assessment",
}

# --- Routing statuses -------------------------------------------------------
SHORTLIST_REVIEW = "SHORTLIST_REVIEW"
MANUAL_REVIEW = "MANUAL_REVIEW"
NOT_SHORTLISTED_REVIEW = "NOT_SHORTLISTED_REVIEW"
ROUTING_STATUSES = (SHORTLIST_REVIEW, MANUAL_REVIEW, NOT_SHORTLISTED_REVIEW)

# --- Human review -----------------------------------------------------------
APPROVE = "APPROVE"
EDIT = "EDIT"
HOLD = "HOLD"
REQUEST_INFO = "REQUEST_INFO"
ACTIONS = (APPROVE, EDIT, HOLD, REQUEST_INFO)

ROLE_ADMIN = "admin"
ROLE_HR_REVIEWER = "hr_reviewer"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ADMIN, ROLE_HR_REVIEWER, ROLE_VIEWER)
ROLE_PERMISSIONS = {
    ROLE_ADMIN: frozenset(ACTIONS),
    ROLE_HR_REVIEWER: frozenset(ACTIONS),
    ROLE_VIEWER: frozenset(),
}

# review_status values written after a (non-blocked) decision
REVIEW_PENDING = "PENDING"
REVIEW_APPROVED = "APPROVED"
REVIEW_EDITED = "EDITED"
REVIEW_ON_HOLD = "ON_HOLD"
REVIEW_INFO_REQUESTED = "INFO_REQUESTED"
# review_status values for blocked attempts (never written to review_decisions.csv)
REVIEW_DENIED = "DENIED"
REVIEW_REJECTED_INPUT = "REVIEW_REJECTED"

# notification_status values
NOTIF_SENT = "SENT"
NOTIF_ALREADY_SENT = "ALREADY_SENT"
NOTIF_RETRYING = "RETRYING"
NOTIF_FAILED = "FAILED"
NOTIF_NOT_REQUIRED = "NOT_REQUIRED"
NOTIF_BLOCKED = "BLOCKED"

MAX_RETRIES = 2  # => at most 3 delivery attempts

# --- Gemini -----------------------------------------------------------------
GEMINI_MODELS = ("gemini-2.5-flash", "gemini-1.5-flash")
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_ENV_VAR = "GEMINI_API_KEY"

# --- Simulation ---------------------------------------------------------------
SIM_REVIEWER_ID = "HR-001"
SIM_REVIEWER_ROLE = ROLE_HR_REVIEWER
SIM_VIEWER_ID = "VIEWER-01"
SIM_FAILURE_ID = "C117"


@dataclass(frozen=True)
class OutputPaths:
    """All output file locations, derived from a single outputs directory."""

    outputs_dir: Path
    rejected: Path
    audit: Path
    sent: Path
    reviews: Path
    results_json: Path
    scored_csv: Path

    @classmethod
    def from_dir(cls, outputs_dir: str | Path | None = None) -> "OutputPaths":
        d = Path(outputs_dir) if outputs_dir is not None else DEFAULT_OUTPUTS_DIR
        return cls(
            outputs_dir=d,
            rejected=d / "rejected_records.csv",
            audit=d / "audit_log.csv",
            sent=d / "sent_notifications.csv",
            reviews=d / "review_decisions.csv",
            results_json=d / "pipeline_results.json",
            scored_csv=d / "scored_candidates.csv",
        )

    def all_files(self) -> list[Path]:
        return [self.rejected, self.audit, self.sent, self.reviews, self.results_json, self.scored_csv]


def get_output_paths(outputs_dir: str | Path | None = None) -> OutputPaths:
    return OutputPaths.from_dir(outputs_dir)


def reset_outputs(outputs_dir: str | Path | None = None) -> OutputPaths:
    """Delete all known output files (fresh run) and ensure the directory exists."""
    paths = OutputPaths.from_dir(outputs_dir)
    paths.outputs_dir.mkdir(parents=True, exist_ok=True)
    for f in paths.all_files():
        if f.exists():
            f.unlink()
    return paths
