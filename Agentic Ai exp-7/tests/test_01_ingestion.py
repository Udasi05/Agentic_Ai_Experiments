import csv
from decimal import Decimal
import pytest
from recruitment.errors import WorkflowError
from recruitment.ingestion import (
    load_candidates,
    validate_candidate,
    normalize_candidate,
    ingest,
    count_duplicates,
    write_rejected,
)
from recruitment.config import DEFAULT_DATA_PATH

def test_01_load_valid_file():
    candidates = load_candidates(DEFAULT_DATA_PATH)
    assert len(candidates) == 120
    assert candidates[0]["candidate_id"] == "C101"
    assert candidates[0]["row"] == 2

def test_02_load_missing_file(tmp_path):
    missing = tmp_path / "nonexistent.csv"
    with pytest.raises(WorkflowError, match="Candidate file not found"):
        load_candidates(missing)

def test_03_load_missing_headers(tmp_path):
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("candidate_id,name\nC001,John\n", encoding="utf-8")
    with pytest.raises(WorkflowError, match="missing required column"):
        load_candidates(bad_csv)

def test_04_validate_valid_record():
    cand = {
        "candidate_id": "C999",
        "name": "Jane Doe",
        "email": "jane@example.com",
        "role": "Software Engineer",
        "skills_score": "80",
        "experience_score": "75",
        "assessment_score": "90",
        "cover_note": "Hello",
    }
    ok, reason = validate_candidate(cand)
    assert ok is True
    assert reason == ""

def test_05_validate_missing_field():
    cand = {
        "candidate_id": "C999",
        "name": "Jane Doe",
        "email": "",
        "role": "Software Engineer",
        "skills_score": "80",
        "experience_score": "75",
        "assessment_score": "90",
    }
    ok, reason = validate_candidate(cand)
    assert ok is False
    assert reason == "Missing field: email"

def test_06_validate_score_out_of_range():
    cand = {
        "candidate_id": "C999",
        "name": "Jane",
        "email": "j@ex.com",
        "role": "SWE",
        "skills_score": "105",
        "experience_score": "50",
        "assessment_score": "50",
    }
    ok, reason = validate_candidate(cand)
    assert ok is False
    assert reason == "skills_score must be between 0 and 100"

def test_07_validate_score_non_numeric():
    cand = {
        "candidate_id": "C999",
        "name": "Jane",
        "email": "j@ex.com",
        "role": "SWE",
        "skills_score": "eighty",
        "experience_score": "50",
        "assessment_score": "50",
    }
    ok, reason = validate_candidate(cand)
    assert ok is False
    assert reason == "Invalid numeric value: skills_score"

def test_08_duplicate_detection_flagged_not_deleted():
    rows = [
        {"row": 2, "candidate_id": "C01", "name": "A", "email": "a@x.com", "role": "SWE", "skills_score": "80", "experience_score": "80", "assessment_score": "80", "cover_note": ""},
        {"row": 3, "candidate_id": "C01", "name": "A2", "email": "a2@x.com", "role": "SWE", "skills_score": "80", "experience_score": "80", "assessment_score": "80", "cover_note": ""},
    ]
    valid, rejected = ingest(rows)
    assert len(valid) == 1
    assert len(rejected) == 1
    assert rejected[0]["candidate_id"] == "C01"
    assert "Duplicate candidate_id" in rejected[0]["reason"]
    assert "first seen at row 2" in rejected[0]["reason"]

def test_09_ingest_exact_counts_on_dataset():
    candidates = load_candidates(DEFAULT_DATA_PATH)
    valid, rejected = ingest(candidates)
    assert len(candidates) == 120
    assert len(valid) == 110
    assert len(rejected) == 10
    assert count_duplicates(rejected) == 3

def test_10_write_rejected_records_csv(tmp_path):
    out_file = tmp_path / "rejected.csv"
    recs = [{"row": 102, "candidate_id": "C201", "reason": "Missing field: email"}]
    write_rejected(recs, out_file)
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "Missing field: email" in content
    assert "C201" in content

