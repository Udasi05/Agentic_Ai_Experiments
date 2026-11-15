"""Functional, failure, security and performance tests for Experiment 5."""
import pytest

from ecommerce_agents import PipelineConfig, apply_human_decision, logic, run_pipeline
from ecommerce_agents.errors import InvalidInputError
from ecommerce_agents.evaluation import (COMBINED_INJECTION_QUERY, DEFAULT_QUERY, run_failure_tests,
                                         run_functional_tests, run_performance_comparison, run_security_tests)

FAST = dict(search_latency=0.01, tool_timeout=0.5, retry_backoff=0.0)


def _ids(rows):
    return [r["Test"] for r in rows if r["Result"] != "PASS"]


def test_functional_suite():
    rows = run_functional_tests()
    assert not _ids(rows), _ids(rows)


def test_failure_suite():
    rows = run_failure_tests()
    assert not _ids(rows), _ids(rows)


def test_security_suite():
    rows = run_security_tests()
    assert not _ids(rows), _ids(rows)


def test_expected_requirements_table():
    req = logic.parse_query(DEFAULT_QUERY)["requirements"]
    assert (req["category"], req["max_price"], req["min_ram_gb"], req["min_storage_gb"], req["min_rating"]) == \
        ("laptop", 70000, 16, 512, 4.2)


@pytest.mark.parametrize("query,expected", [
    ("phone below 45k with 12 GB RAM", {"category": "smartphone", "max_price": 45000, "min_ram_gb": 12}),
    ("laptop within 1.2 lakh with 1 TB SSD", {"category": "laptop", "max_price": 120000, "min_storage_gb": 1024}),
    ("tablet under Rs 30,000 rated at least 4.4", {"category": "tablet", "max_price": 30000, "min_rating": 4.4}),
    ("Lenovo notebook 4.5 stars", {"category": "laptop", "brands": ["Lenovo"], "min_rating": 4.5}),
])
def test_parser_variants(query, expected):
    req = logic.parse_query(query)["requirements"]
    for k, v in expected.items():
        assert req[k] == v, (k, req)


def test_out_of_range_rating_rejected():
    with pytest.raises(InvalidInputError):
        logic.parse_query("laptop rating above 7")


def test_expected_ranking_and_approval():
    st = run_pipeline(DEFAULT_QUERY, PipelineConfig(**FAST))
    ranked = [r["product_id"] for r in st.read("ranking")]
    assert set(ranked) == {"L001", "L002", "L003", "L007", "L008", "L011", "L014"}
    assert st.status == "AWAITING_HUMAN_APPROVAL"
    st = apply_human_decision(st, "approve", "Tester")
    assert st.status == "COMPLETED"
    assert st.read("final_recommendation")["top_pick"]["product_id"] == ranked[0]
    with pytest.raises(InvalidInputError):  # second decision is refused
        apply_human_decision(st, "reject", "Tester")


def test_reject_and_reanalysis_with_exclusion_and_override():
    st = run_pipeline(DEFAULT_QUERY, PipelineConfig(**FAST))
    top = st.read("ranking")[0]["product_id"]
    new = apply_human_decision(st, "reanalyze", "Tester", "top pick has wrong specs", [top], {"max_price": 65000})
    assert st.status == "REANALYSIS_REQUESTED"
    assert new.read("parent_workflow_id") == st.workflow_id
    assert new.read("requirements")["max_price"] == 65000
    ranked = [r for r in new.read("ranking")]
    assert top not in [r["product_id"] for r in ranked]
    assert all(r["price"] <= 65000 for r in ranked)
    assert new.read("metrics")["tool_cache_hits"] == 3  # searches reused, not repeated
    st2 = run_pipeline(DEFAULT_QUERY, PipelineConfig(**FAST))
    apply_human_decision(st2, "reject", "Tester")
    assert st2.status == "REJECTED" and st2.read("final_recommendation") is None


def test_cannot_approve_unvalidated():
    st = run_pipeline("Laptops under ₹20,000 with 32 GB RAM", PipelineConfig(**FAST))
    assert st.status == "NO_RESULTS"
    with pytest.raises(InvalidInputError):
        apply_human_decision(st, "approve", "Tester")


def test_injection_does_not_change_result():
    clean = run_pipeline(DEFAULT_QUERY, PipelineConfig(**FAST))
    injected = run_pipeline(COMBINED_INJECTION_QUERY, PipelineConfig(**FAST))
    assert [r["product_id"] for r in clean.read("ranking")] == [r["product_id"] for r in injected.read("ranking")]


def test_sequential_and_parallel_agree_and_parallel_is_faster():
    perf = run_performance_comparison(DEFAULT_QUERY, search_latency=0.2, runs=1)
    s = perf["summary"]
    assert s["same_result"]
    assert s["speedup_search_stage"] > 1.8
    seq = [r for r in perf["runs"] if r["Mode"] == "sequential"][0]
    par = [r for r in perf["runs"] if r["Mode"] == "parallel"][0]
    assert seq["Agent executions"] == par["Agent executions"] and seq["Tool calls"] == par["Tool calls"]


def test_trace_and_messages_recorded():
    st = run_pipeline(DEFAULT_QUERY, PipelineConfig(**FAST))
    trace = st.read("trace")
    agents = {t["agent"] for t in trace}
    assert {"Planner Agent", "Router Agent", "Search Agent A", "Search Agent B", "Search Agent C", "Filter Agent",
            "Comparison Agent", "Ranking Agent", "Validator Agent", "Supervisor Agent"} <= agents
    for t in trace:
        assert {"agent", "task", "start", "end", "status", "tools", "retries", "error", "output_status"} <= set(t)
    assert len(st.read("messages")) > 10
    m = st.read("metrics")
    assert m["num_agents_executed"] == 10 and m["cost_units"] > 0
