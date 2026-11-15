import pytest
from recruitment.drafts import (
    generate_draft,
    validate_polished,
    polish_draft,
    FORBIDDEN_PHRASES,
)

def test_21_draft_generation_shortlist():
    cand = {"candidate_id": "C101", "name": "Aarav Shah", "role": "Software Engineer"}
    draft = generate_draft(cand, "SHORTLIST_REVIEW")
    assert draft["label"] == "DRAFT"
    assert "Application reference: C101" in draft["message"]
    assert "82" not in draft["message"]  # scores hidden
    ok, reason = validate_polished(draft["message"], cand)
    assert ok is True

def test_22_draft_generation_manual():
    cand = {"candidate_id": "C102", "name": "Diya Mehta", "role": "Software Engineer"}
    draft = generate_draft(cand, "MANUAL_REVIEW")
    assert draft["label"] == "DRAFT"
    assert "Application reference: C102" in draft["message"]
    ok, reason = validate_polished(draft["message"], cand)
    assert ok is True

def test_23_draft_generation_not_shortlisted():
    cand = {"candidate_id": "C105", "name": "Neel Joshi", "role": "Software Engineer"}
    draft = generate_draft(cand, "NOT_SHORTLISTED_REVIEW")
    assert draft["label"] == "DRAFT"
    assert "Application reference: C105" in draft["message"]
    # Never imply final rejection
    assert "rejected" not in draft["message"].lower()
    ok, reason = validate_polished(draft["message"], cand)
    assert ok is True

def test_24_guard_rejects_forbidden_words():
    cand = {"candidate_id": "C101"}
    bad_text = "Dear Aarav,\nWe regret to inform you that you were rejected.\nApplication reference: C101"
    ok, reason = validate_polished(bad_text, cand)
    assert ok is False
    assert "Forbidden language" in reason

def test_25_guard_rejects_score_disclosure():
    cand = {"candidate_id": "C101"}
    bad_text = "Dear Aarav,\nYour rating is 82 across our benchmark.\nApplication reference: C101"
    ok, reason = validate_polished(bad_text, cand)
    assert ok is False
    assert "Contains numeric value" in reason

def test_26_guard_rejects_missing_reference():
    cand = {"candidate_id": "C101"}
    bad_text = "Dear Aarav,\nYour application is being considered by HR."
    ok, reason = validate_polished(bad_text, cand)
    assert ok is False
    assert "Missing application reference line" in reason

def test_27_guard_allows_valid_polished_text():
    cand = {"candidate_id": "C101"}
    valid_text = (
        "Dear Aarav Shah,\n\n"
        "Thank you for taking the time to speak with our engineering team. "
        "We are currently reviewing your profile for the next stage.\n\n"
        "Application reference: C101\n\n"
        "Best regards,\nRecruitment Team"
    )
    ok, reason = validate_polished(valid_text, cand)
    assert ok is True

def test_28_polish_draft_fallback_without_api_key():
    cand = {"candidate_id": "C101", "name": "Aarav", "role": "SWE"}
    draft = generate_draft(cand, "SHORTLIST_REVIEW")
    res = polish_draft(draft, cand, api_key=None)
    assert res["polish_status"] == "FALLBACK"
    assert "GEMINI_API_KEY" in res["polish_reason"]
    assert res["message"] == draft["message"]

def test_29_polish_draft_with_mock_client_success():
    cand = {"candidate_id": "C101", "name": "Aarav", "role": "SWE"}
    draft = generate_draft(cand, "SHORTLIST_REVIEW")

    class MockContent:
        text = "Polished message without numbers or bad words.\nApplication reference: C101"

    class MockModels:
        def generate_content(self, model, contents):
            return MockContent()

    class MockClient:
        models = MockModels()

    res = polish_draft(draft, cand, client=MockClient())
    assert res["polish_status"] == "POLISHED"
    assert res["source"] == "gemini"
    assert "Polished message" in res["message"]

def test_30_polish_draft_with_mock_client_violating_guard():
    cand = {"candidate_id": "C101", "name": "Aarav", "role": "SWE"}
    draft = generate_draft(cand, "SHORTLIST_REVIEW")

    class MockContent:
        text = "You got rejected with score 99.\nApplication reference: C101"

    class MockModels:
        def generate_content(self, model, contents):
            return MockContent()

    class MockClient:
        models = MockModels()

    res = polish_draft(draft, cand, client=MockClient())
    assert res["polish_status"] == "FALLBACK"
    assert "Guard rejected" in res["polish_reason"]
    assert res["message"] == draft["message"]
