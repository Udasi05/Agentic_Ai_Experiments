import pytest
from recruitment.config import DEFAULT_DATA_PATH, DEFAULT_RULES_PATH
from recruitment.pipeline_graph import run_pipeline, load_pipeline_results
from recruitment.review_graph import authorize, access_denied_message, run_review, load_review_decisions
from recruitment.simulation import run_simulation
from recruitment.metrics import compute_metrics, format_metrics, metrics_from_outputs
from recruitment.errors import WorkflowError

def test_37_pipeline_graph_execution(tmp_path):
    res = run_pipeline(
        csv_path=DEFAULT_DATA_PATH,
        rules_path=DEFAULT_RULES_PATH,
        outputs_dir=tmp_path,
        reset=True
    )
    assert res["status"] == "COMPLETED"
    assert res["total_loaded"] == 120
    assert res["valid_count"] == 110
    assert res["rejected_count"] == 10
    assert res["status_counts"]["SHORTLIST_REVIEW"] == 31
    assert res["status_counts"]["MANUAL_REVIEW"] == 51
    assert res["status_counts"]["NOT_SHORTLISTED_REVIEW"] == 28

def test_38_pipeline_graph_failure_branch_missing_file(tmp_path):
    res = run_pipeline(
        csv_path="nonexistent_candidates.csv",
        rules_path=DEFAULT_RULES_PATH,
        outputs_dir=tmp_path,
        reset=True
    )
    assert res["status"] == "FAILED"
    assert res["failed_stage"] == "ingest"
    assert "not found" in res["error"].lower()

def test_39_pipeline_graph_failure_branch_bad_rules(tmp_path):
    bad_rules = tmp_path / "bad_rules.json"
    bad_rules.write_text('{"rule_version": "v1"}', encoding="utf-8")
    res = run_pipeline(
        csv_path=DEFAULT_DATA_PATH,
        rules_path=bad_rules,
        outputs_dir=tmp_path,
        reset=True
    )
    assert res["status"] == "FAILED"
    assert res["failed_stage"] == "load_rules"

def test_40_load_pipeline_results_persistence(tmp_path):
    run_pipeline(DEFAULT_DATA_PATH, DEFAULT_RULES_PATH, tmp_path, reset=True)
    loaded = load_pipeline_results(tmp_path)
    assert loaded["status"] == "COMPLETED"
    assert loaded["valid_count"] == 110
    assert len(loaded["results"]) == 110

def test_41_authorize_roles_and_actions():
    assert authorize("admin", "APPROVE") is True
    assert authorize("hr_reviewer", "APPROVE") is True
    assert authorize("hr_reviewer", "EDIT") is True
    assert authorize("hr_reviewer", "HOLD") is True
    assert authorize("hr_reviewer", "REQUEST_INFO") is True
    assert authorize("viewer", "APPROVE") is False
    assert authorize("viewer", "HOLD") is False
    assert authorize("unknown", "APPROVE") is False

def test_42_access_denied_message():
    msg = access_denied_message("viewer", "APPROVE")
    assert msg == "Access Denied: Role 'viewer' may not perform APPROVE"

def test_43_review_graph_unauthorized_blocked(tmp_path):
    run_pipeline(DEFAULT_DATA_PATH, DEFAULT_RULES_PATH, tmp_path, reset=True)
    res = run_review(
        candidate_id="C104",
        reviewer_id="VIEWER-01",
        role="viewer",
        action="APPROVE",
        outputs_dir=tmp_path
    )
    assert res["blocked"] is True
    assert res["block_event"] == "ACCESS_DENIED"
    assert res["review_status"] == "DENIED"

def test_44_review_graph_approve_action(tmp_path):
    run_pipeline(DEFAULT_DATA_PATH, DEFAULT_RULES_PATH, tmp_path, reset=True)
    res = run_review(
        candidate_id="C101",
        reviewer_id="HR-001",
        role="hr_reviewer",
        action="APPROVE",
        outputs_dir=tmp_path
    )
    assert res["blocked"] is False
    assert res["review_status"] == "APPROVED"
    assert res["notification_status"] == "SENT"

def test_45_review_graph_edit_action_override(tmp_path):
    run_pipeline(DEFAULT_DATA_PATH, DEFAULT_RULES_PATH, tmp_path, reset=True)
    res = run_review(
        candidate_id="C103",
        reviewer_id="HR-001",
        role="hr_reviewer",
        action="EDIT",
        override_status="MANUAL_REVIEW",
        reason="Strong open-source contributions",
        outputs_dir=tmp_path
    )
    assert res["blocked"] is False
    assert res["review_status"] == "EDITED"
    assert res["final_status"] == "MANUAL_REVIEW"
    assert res["notification_status"] == "NOT_REQUIRED"

def test_46_review_graph_edit_without_reason_rejected(tmp_path):
    run_pipeline(DEFAULT_DATA_PATH, DEFAULT_RULES_PATH, tmp_path, reset=True)
    res = run_review(
        candidate_id="C103",
        reviewer_id="HR-001",
        role="hr_reviewer",
        action="EDIT",
        override_status="MANUAL_REVIEW",
        reason="",  # Missing required reason
        outputs_dir=tmp_path
    )
    assert res["blocked"] is True
    assert res["block_event"] == "REVIEW_REJECTED"
    assert "reason" in res["block_reason"]

def test_47_review_graph_hold_action(tmp_path):
    run_pipeline(DEFAULT_DATA_PATH, DEFAULT_RULES_PATH, tmp_path, reset=True)
    res = run_review(
        candidate_id="C102",
        reviewer_id="HR-001",
        role="hr_reviewer",
        action="HOLD",
        notes="Waiting for background verification",
        outputs_dir=tmp_path
    )
    assert res["blocked"] is False
    assert res["review_status"] == "ON_HOLD"
    assert res["notification_status"] == "NOT_REQUIRED"

def test_48_review_graph_retry_and_permanent_failure(tmp_path):
    run_pipeline(DEFAULT_DATA_PATH, DEFAULT_RULES_PATH, tmp_path, reset=True)
    # C117 is configured to simulate failure
    from recruitment.notifications import NotificationDispatcher
    dispatcher = NotificationDispatcher(tmp_path / "sent_notifications.csv", fail_ids=["C117"])
    res = run_review(
        candidate_id="C117",
        reviewer_id="HR-001",
        role="hr_reviewer",
        action="APPROVE",
        outputs_dir=tmp_path,
        dispatcher=dispatcher
    )
    assert res["notification_status"] == "FAILED"
    assert res["attempts"] == 3  # Initial + 2 retries

def test_49_full_simulation_run(tmp_path):
    p = run_pipeline(DEFAULT_DATA_PATH, DEFAULT_RULES_PATH, tmp_path, reset=True)
    sim = run_simulation(outputs_dir=tmp_path, pipeline=p)
    summ = sim["summary"]
    assert summ["decisions"] == 110
    assert summ["approvals"] == 108
    assert summ["holds"] == 1
    assert summ["edits"] == 1
    assert summ["denied"] == 1
    assert summ["sent"] == 107
    assert summ["failed"] == 1

def test_50_metrics_computation(tmp_path):
    p = run_pipeline(DEFAULT_DATA_PATH, DEFAULT_RULES_PATH, tmp_path, reset=True)
    sim = run_simulation(outputs_dir=tmp_path, pipeline=p)
    m = compute_metrics(p, sim["summary"], test_results=(50, 50))
    formatted = dict(format_metrics(m))
    
    assert formatted["Records loaded / valid / quarantined"] == "120 / 110 / 10"
    assert formatted["Duplicates"] == "3"
    assert formatted["Shortlist / Manual / Not shortlisted"] == "31 / 51 / 28"
    assert formatted["Drafts generated"] == "110"
    assert formatted["Approvals / Holds / Edits"] == "108 / 1 / 1"
    assert formatted["Notifications sent / failed"] == "107 / 1"
    assert formatted["Unauthorized attempts denied"] == "1"
    assert formatted["Data validation rate"] == "91.7%"
    assert formatted["Workflow success rate"] == "100%"
    assert formatted["Draft generation rate"] == "100%"
    assert formatted["Human review completion rate"] == "100%"
    assert formatted["Test pass rate"] == "100% (50/50)"
    assert "Identical (110/110)" in formatted["Score consistency on re-run"]

