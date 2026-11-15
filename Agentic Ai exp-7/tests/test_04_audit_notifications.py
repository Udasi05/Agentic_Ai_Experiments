import pytest
from recruitment.audit import AuditLogger, read_audit_log, AUDIT_FIELDS
from recruitment.notifications import NotificationDispatcher, load_sent
from recruitment.errors import DeliveryError

def test_31_audit_logger_creates_and_appends(tmp_path):
    log_file = tmp_path / "audit.csv"
    logger = AuditLogger(log_file, run_id="RUN-TEST-1")
    logger.log("RUN_STARTED", details="Starting pipeline")
    logger.log("CANDIDATE_SCORED", candidate_id="C101", status="VALID")
    
    records = read_audit_log(log_file)
    assert len(records) == 2
    assert records[0]["event"] == "RUN_STARTED"
    assert records[1]["candidate_id"] == "C101"
    assert set(records[0].keys()) == set(AUDIT_FIELDS)

def test_32_audit_logger_data_minimization(tmp_path):
    log_file = tmp_path / "audit.csv"
    logger = AuditLogger(log_file, run_id="RUN-TEST-2")
    logger.register_sensitive(["Aarav Shah", "aarav@example.com"])
    
    # Try logging personal details in details field
    logger.log("RECORD_QUARANTINED", candidate_id="C101", details="Issue with Aarav Shah at aarav@example.com")
    
    records = read_audit_log(log_file)
    content = log_file.read_text(encoding="utf-8")
    assert "Aarav Shah" not in content
    assert "aarav@example.com" not in content
    assert "[REDACTED]" in records[0]["details"]

def test_33_notification_dispatcher_send_success(tmp_path):
    sent_file = tmp_path / "sent.csv"
    dispatcher = NotificationDispatcher(sent_file)
    res = dispatcher.send("C101", "SHORTLIST_REVIEW", "Subject", "Message", "HR-001")
    assert res["status"] == "SHORTLIST_REVIEW"
    assert dispatcher.already_sent("C101") is True
    
    sent = load_sent(sent_file)
    assert len(sent) == 1
    assert sent[0]["candidate_id"] == "C101"

def test_34_notification_dispatcher_simulated_failure(tmp_path):
    sent_file = tmp_path / "sent.csv"
    dispatcher = NotificationDispatcher(sent_file, fail_ids=["C117"])
    with pytest.raises(DeliveryError):
        dispatcher.send("C117", "SHORTLIST_REVIEW", "Subject", "Message", "HR-001")
    assert dispatcher.already_sent("C117") is False

def test_35_notification_dispatcher_transient_failure(tmp_path):
    sent_file = tmp_path / "sent.csv"
    dispatcher = NotificationDispatcher(sent_file, transient_failures={"C101": 2})
    # Attempt 1 -> fail
    with pytest.raises(DeliveryError):
        dispatcher.send("C101", "SHORTLIST_REVIEW", "Subject", "Message", "HR-001", attempt=1)
    # Attempt 2 -> fail
    with pytest.raises(DeliveryError):
        dispatcher.send("C101", "SHORTLIST_REVIEW", "Subject", "Message", "HR-001", attempt=2)
    # Attempt 3 -> succeeds
    res = dispatcher.send("C101", "SHORTLIST_REVIEW", "Subject", "Message", "HR-001", attempt=3)
    assert int(res["attempts"]) == 3
    assert dispatcher.already_sent("C101") is True

def test_36_notification_idempotency(tmp_path):
    sent_file = tmp_path / "sent.csv"
    dispatcher = NotificationDispatcher(sent_file)
    dispatcher.send("C101", "SHORTLIST_REVIEW", "Subject", "Message", "HR-001")
    assert dispatcher.already_sent("C101") is True
    sent_ids = dispatcher.sent_ids()
    assert "C101" in sent_ids
