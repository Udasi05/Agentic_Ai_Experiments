"""Test benchmark execution."""

from src.benchmark import get_experiment_baseline_benchmark, run_single_task

def test_run_single_task():
    res = run_single_task("analyze_python", {"file": "calculator.py"})
    assert "calculator.py" in res

def test_benchmark_baseline_data():
    data = get_experiment_baseline_benchmark()
    assert "ro_df" in data
    assert "test_df" in data
    assert "summary_df" in data
    assert data["avg_ro_seq"] == 29.68
    assert data["avg_ro_par"] == 20.65
    assert data["ro_reduction"] == 30.43
    assert data["avg_test_seq"] == 332.44
    assert data["avg_test_par"] == 326.49
    assert data["test_reduction"] == 1.79
