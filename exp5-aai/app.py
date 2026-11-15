"""Streamlit UI — Experiment 5: E-Commerce Product Analysis & Recommendation Pipeline.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import io
import json

import altair as alt
import pandas as pd
import streamlit as st

from ecommerce_agents import data, logic
from ecommerce_agents.agents import AGENT_NAMES, AGENT_RESPONSIBILITIES
from ecommerce_agents.errors import AgentSystemError, InvalidInputError
from ecommerce_agents.evaluation import (DEFAULT_QUERY, EXAMPLE_QUERIES, build_observation_table,
                                         run_failure_tests, run_functional_tests, run_performance_comparison,
                                         run_security_tests)
from ecommerce_agents.observability import LOG_FILE
from ecommerce_agents.orchestrator import COST_WEIGHTS, PipelineConfig, apply_human_decision, run_pipeline
from ecommerce_agents.state import WRITE_PERMISSIONS, WorkflowState
from ecommerce_agents.tools import FailureInjector, build_registry

st.set_page_config(page_title="Exp 5 · Multi-Agent E-Commerce Recommender", page_icon="🛒", layout="wide")

# ------------------------------------------------------------------ session
ss = st.session_state
ss.setdefault("query", DEFAULT_QUERY)
ss.setdefault("wf", None)
ss.setdefault("history", [])
ss.setdefault("perf", None)
ss.setdefault("security", None)
ss.setdefault("functional", None)
ss.setdefault("failure", None)
ss.setdefault("flash", None)

STATUS_STYLE = {
    "AWAITING_HUMAN_APPROVAL": ("warning", "⏳"), "COMPLETED": ("success", "✅"), "REJECTED": ("error", "🚫"),
    "REANALYSIS_REQUESTED": ("info", "🔁"), "NO_RESULTS": ("warning", "🔎"), "VALIDATION_FAILED": ("error", "❌"),
    "FAILED": ("error", "❌"), "BLOCKED_SECURITY": ("error", "🛡️"), "RUNNING": ("info", "⚙️"),
}
TASK_COLORS = {"SUCCESS": "#c8f7c5", "FAILED": "#f8c0c0", "SKIPPED": "#e0e0e0", "RUNNING": "#fff3b0", None: "#ffffff"}


def to_df(rows) -> pd.DataFrame:
    """DataFrame with nested values stringified (keeps Arrow serialization safe)."""
    df = pd.DataFrame(rows)
    for col in df.columns:
        if df[col].map(lambda v: isinstance(v, (dict, list, tuple, set))).any():
            df[col] = df[col].map(lambda v: json.dumps(v, ensure_ascii=False, default=str)
                                  if isinstance(v, (dict, list, tuple, set)) else v)
    return df


def show_table(rows, **kw):
    if not rows:
        st.caption("— none —")
        return
    st.dataframe(to_df(rows), hide_index=True, **kw)


def result_style(df: pd.DataFrame):
    def color(v):
        return "background-color:#c8f7c5" if v == "PASS" else ("background-color:#f8c0c0" if v == "FAIL" else "")
    return df.style.map(color, subset=["Result"])


def status_banner(status: str, text: str):
    kind, icon = STATUS_STYLE.get(status, ("info", "ℹ️"))
    getattr(st, kind)(f"{icon} **{status}** — {text}")


def workflow_dot(state: WorkflowState) -> str:
    ts = state.read("task_status")
    plan = state.read("plan")
    routing = state.read("routing") or {}
    labels = {"P0": "Planner Agent\\nP0", "CP1": "Validator Agent\\nCP1 requirements", "R0": "Router Agent\\nR0"}
    edges = [("P0", "CP1"), ("CP1", "R0")]
    if plan:
        for t in plan["tasks"]:
            agent = routing.get("assignments", {}).get(t["task_id"], "?")
            labels[t["task_id"]] = f"{agent}\\n{t['task_id']}: {t['type']}"
            for d in t["depends_on"]:
                edges.append((d, t["task_id"]))
            if not t["depends_on"]:
                edges.append(("R0", t["task_id"]))
        edges.append(("T10", "HUMAN"))
    approval = state.read("human_approval")
    lines = ["digraph G {", 'rankdir=LR; node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10];']
    for nid, lab in labels.items():
        lines.append(f'"{nid}" [label="{lab}", fillcolor="{TASK_COLORS.get(ts.get(nid), "#ffffff")}"];')
    if plan:
        hcol = "#c8f7c5" if approval and approval["decision"] == "APPROVE" else ("#f8c0c0" if approval and approval["decision"] == "REJECT" else "#fff3b0")
        hlab = f"Human Reviewer\\n{approval['decision'] if approval else 'pending'}"
        lines.append(f'"HUMAN" [label="{hlab}", shape=ellipse, fillcolor="{hcol}"];')
    if plan:
        lines.append('{rank=same; "T1"; "T2"; "T3";}')
    for a, b in edges:
        lines.append(f'"{a}" -> "{b}";')
    lines.append("}")
    return "\n".join(lines)


ARCH_DOT = """
digraph A {
rankdir=TB; node [shape=box, style="rounded,filled", fillcolor="#eef3ff", fontname="Helvetica", fontsize=10];
U [label="Customer query", shape=ellipse, fillcolor="#ffffff"];
P [label="Planner Agent\\n(query_parser)"]; V1 [label="Validator\\ncheckpoint 1"]; R [label="Router Agent\\n(dependency-aware)"];
SA [label="Search Agent A\\n(product_search)"]; SB [label="Search Agent B\\n(product_search)"]; SC [label="Search Agent C\\n(product_search)"];
SY [label="Supervisor: Synchronize\\n+ conflict resolution"]; F [label="Filter Agent\\n(filter_products)"];
V2 [label="Validator\\ncheckpoint 2"]; C [label="Comparison Agent\\n(compare_products)"]; RK [label="Ranking Agent\\n(score_products)"];
V3 [label="Validator\\nfinal"]; S [label="Supervisor Agent\\n(monitor, escalate)"]; H [label="Human Approval", shape=ellipse, fillcolor="#fff3b0"];
FR [label="Final Recommendation", shape=ellipse, fillcolor="#c8f7c5"];
STATE [label="Shared Workflow State\\n(role-based writes, integrity hash)", shape=cylinder, fillcolor="#f5f5f5"];
REG [label="MCP-style Tool Registry\\n(discovery, authz, schema, timeout, cache)", shape=component, fillcolor="#f5f5f5"];
U -> P -> V1 -> R; R -> SA; R -> SB; R -> SC; SA -> SY; SB -> SY; SC -> SY; SY -> F -> V2 -> C -> RK -> V3 -> S -> H -> FR;
H -> P [label="re-analysis", style=dashed];
{rank=same; SA; SB; SC;}
STATE -> S [style=dotted, arrowhead=none]; REG -> F [style=dotted, arrowhead=none];
}
"""


def config_from_sidebar() -> PipelineConfig:
    with st.sidebar:
        st.header("⚙️ Run configuration")

        def _pick_example():
            ss.query = ss.example_pick

        st.selectbox("Example queries", EXAMPLE_QUERIES, key="example_pick", on_change=_pick_example)
        st.text_area("Customer request (natural language)", key="query", max_chars=logic.MAX_QUERY_LEN, height=110)
        mode = st.radio("Execution mode", ["parallel", "sequential"], horizontal=True,
                        help="Parallel runs the independent Search Agents concurrently.")
        latency = st.slider("Simulated catalog latency (s)", 0.0, 1.0, 0.3, 0.05)
        timeout = st.slider("Tool timeout (s)", 0.5, 5.0, 2.0, 0.25)
        retries = st.slider("Max retries per agent", 0, 5, 2)
        failure_opts = {"None": [], "Transient ×1": ["transient"], "Transient ×2": ["transient"] * 2,
                        "Timeout ×1": ["timeout"], "Transient ×6 (exhaust retries)": ["transient"] * 6,
                        "Permanent": ["permanent"]}
        failures: dict = {}
        with st.expander("🧪 Failure injection"):
            for src, meta in data.SOURCES.items():
                choice = st.selectbox(f"Source {src} · {meta['name']}", list(failure_opts), key=f"fail_{src}")
                if failure_opts[choice]:
                    failures[f"search:{src}"] = failure_opts[choice]
            agent = st.selectbox("Agent crash", ["None", "Filter Agent", "Comparison Agent", "Ranking Agent", "Validator Agent"])
            kind = st.selectbox("Agent crash type", ["Transient ×1", "Permanent"])
            if agent != "None":
                failures[f"agent:{agent}"] = ["transient"] if kind == "Transient ×1" else ["permanent"]
        with st.expander("🛡️ Security demo"):
            tamper = st.checkbox("Simulate compromised component tampering with budget after planning")
        if latency >= timeout:
            st.warning("Latency ≥ timeout: every search call will time out.")
    return PipelineConfig(mode=mode, search_latency=latency, tool_timeout=timeout, max_retries=retries,
                          failures=failures, tamper_after_planning=tamper)


def set_workflow(new_state: WorkflowState):
    ss.wf = new_state
    ss.history.append(new_state)


# ======================================================================= UI
cfg = config_from_sidebar()
st.title("🛒 Multi-Agent E-Commerce Product Analysis & Recommendation Pipeline")
st.caption("Experiment 5 · CO4 (multi-agent concurrency & coordination) · CO5 (human-in-the-loop governance). "
           "Specialized agents plan, route, search, filter, compare, rank, validate and supervise; a human approves.")

if st.sidebar.button("▶ Run pipeline", type="primary", width="stretch"):
    try:
        with st.spinner("Agents working…"):
            set_workflow(run_pipeline(ss.query, cfg))
        ss.flash = None
    except InvalidInputError as e:
        st.sidebar.error(str(e))

if ss.flash:
    st.toast(ss.flash)
    ss.flash = None

tabs = st.tabs(["🧭 Pipeline", "✅ Human Approval", "🔍 Trace & Communication", "⚡ Performance",
                "🛡️ Security Tests", "🧪 Functional & Failure Tests", "🧰 MCP-style Tools",
                "📋 Observation Table", "📐 Architecture", "🗂️ History"])

wf: WorkflowState | None = ss.wf

# ------------------------------------------------------------------ Pipeline
with tabs[0]:
    if wf is None:
        st.info("Configure the request in the sidebar and click **▶ Run pipeline**.")
    else:
        snap = wf.snapshot()
        m = snap["metrics"]
        decision = snap["supervisor_decision"] or {}
        status_banner(snap["status"], decision.get("summary", ""))
        c = st.columns(6)
        c[0].metric("Workflow", snap["workflow_id"])
        c[1].metric("Agents (distinct / runs)", f"{m.get('num_agents_executed', 0)} / {m['agent_executions']}")
        c[2].metric("Tool calls", m["tool_calls"], help=f"cache hits {m['tool_cache_hits']}, denied {m['tool_denials']}")
        c[3].metric("Retries", m["retries"])
        c[4].metric("Total time", f"{m.get('total_time_s', 0):.3f} s", help=f"mode = {snap['mode']}")
        c[5].metric("Cost units", m.get("cost_units", 0))
        if snap["parent_workflow_id"]:
            st.caption(f"Re-analysis of {snap['parent_workflow_id']}")

        st.subheader("1 · Planner Agent — query decomposition")
        left, right = st.columns([1, 1])
        with left:
            st.markdown(f"**User query:** {snap['user_query']}")
            if snap["requirements"]:
                show_table(logic.describe_requirements(snap["requirements"]))
            for f in snap["security_flags"]:
                st.warning(f"🛡️ Prompt injection neutralized: “{f['clause']}” → {f['action']}")
        with right:
            if snap["routing"]:
                st.markdown("**Router Agent — dependency-aware execution levels**")
                show_table([{"Level": s["level"], "Tasks": ", ".join(s["tasks"]), "Agents": ", ".join(s["agents"]),
                             "Execution": s["execution"], "Reason": s["reason"]} for s in snap["routing"]["strategy"]])
        st.graphviz_chart(workflow_dot(wf), width="stretch")

        if snap["search_results"] or snap["task_status"].get("T1"):
            st.subheader("2 · Search Agents (parallel) → Synchronization")
            cols = st.columns(3)
            for i, (src, meta) in enumerate(data.SOURCES.items()):
                tid = f"T{i + 1}"
                res = snap["search_results"].get(src)
                cols[i].metric(f"Source {src} · {meta['name']}",
                               f"{len(res)} products" if res is not None else "—",
                               delta=snap["task_status"].get(tid), delta_color="off")
            with st.expander(f"Synchronized catalog ({len(snap['synchronized_results'])} unique products)"):
                show_table([{k: p.get(k) for k in ("product_id", "name", "brand", "price", "ram_gb", "storage_gb", "rating", "in_stock", "sources")}
                            for p in snap["synchronized_results"]])
            if snap["conflicts"]:
                st.markdown("**Conflict resolution** (agents disagreed on product data)")
                show_table([{"Product": f"{c['product_id']} {c['name']}", "Field": c["field"], "Values by source": c["values"],
                             "Resolved": c["resolved_value"], "From": c["resolved_from"], "Method": c["method"],
                             "Severity": c["severity"]} for c in snap["conflicts"]])

        if snap["task_status"].get("T5"):
            st.subheader("3 · Filter Agent — constraint-based decision making")
            a, b = st.columns(2)
            a.markdown(f"**Passed: {len(snap['filtered_results'])}**")
            with a:
                show_table([{k: p.get(k) for k in ("product_id", "name", "price", "ram_gb", "storage_gb", "rating")} for p in snap["filtered_results"]])
            b.markdown(f"**Rejected: {len(snap['rejected_products'])}**")
            with b:
                show_table([{"Product": f"{r['product_id']} {r['name']}", "Reasons": "; ".join(r["reasons"])} for r in snap["rejected_products"]])

        if snap["comparison"] and snap["comparison"]["rows"]:
            st.subheader("4 · Comparison Agent")
            comp = snap["comparison"]
            name_of = {r["product_id"]: r["name"] for r in comp["rows"]}
            st.caption(" · ".join(f"**{k.replace('_', ' ').title()}:** {name_of.get(v, v)}" for k, v in comp["best_in"].items()))
            show_table([{"Product": f"{r['product_id']} {r['name']}", "Price": logic.fmt_inr(r["price"]),
                         "Budget headroom": logic.fmt_inr(r["budget_headroom"]) if r["budget_headroom"] is not None else "—",
                         "RAM": r["ram_gb"], "RAM margin": r["ram_margin_gb"], "Storage": r["storage_gb"],
                         "Storage margin": r["storage_margin_gb"], "Rating": r["rating"], "Rating margin": r["rating_margin"],
                         "Processor": r["processor"], "Display": r["display"]} for r in comp["rows"]])

        if snap["ranking"]:
            st.subheader("5 · Ranking Agent — transparent requirement-aware scoring")
            w = snap["ranking"][0]["weights"]
            st.caption("Score = 100 × Σ weightᵢ × normalizedᵢ (min-max across qualifying products; price inverted). "
                       f"Weights (requested factors ×{logic.REQUIREMENT_BOOST}): " + ", ".join(f"{k} {v:.2%}" for k, v in w.items()))
            show_table([{"Rank": r["rank"], "Product": r["name"], "ID": r["product_id"], "Price": logic.fmt_inr(r["price"]),
                         "RAM": r["ram_gb"], "Storage": r["storage_gb"], "Rating": r["rating"], "Score": r["score"],
                         **{f"{k} pts": v for k, v in r["contributions"].items()}} for r in snap["ranking"]])
            long = [{"Product": f"#{r['rank']} {r['name']}", "Factor": k, "Points": v, "order": r["rank"]}
                    for r in snap["ranking"] for k, v in r["contributions"].items()]
            chart = (alt.Chart(pd.DataFrame(long)).mark_bar()
                     .encode(x=alt.X("sum(Points):Q", title="Score"),
                             y=alt.Y("Product:N", sort=alt.SortField("order"), title=None),
                             color=alt.Color("Factor:N"), tooltip=["Product", "Factor", "Points"])
                     .properties(height=40 + 28 * len(snap["ranking"])))
            st.altair_chart(chart, width="stretch")
            for r in snap["ranking"][:3]:
                with st.expander(f"Why #{r['rank']} {r['name']}? (score {r['score']})"):
                    for reason in r["reasons"]:
                        st.markdown(f"- {reason}")

        if snap["validation"]:
            st.subheader("6 · Validator Agent — checkpoint validation")
            for key, v in snap["validation"].items():
                icon = "✅" if v["passed"] else "❌"
                with st.expander(f"{icon} {v['checkpoint']} — {'PASSED' if v['passed'] else 'FAILED'} ({len(v['checks'])} checks)"):
                    show_table(v["checks"])

        if decision:
            st.subheader("7 · Supervisor Agent")
            st.markdown(f"**Decision:** `{decision['action']}` → `{decision['status']}`")
            for r in decision["escalation_reasons"]:
                st.markdown(f"- {r}")
            if decision["failed_tasks"] or decision["skipped_tasks"]:
                st.markdown(f"Failed tasks: `{decision['failed_tasks']}` · Skipped: `{decision['skipped_tasks']}`")

        final = snap["final_recommendation"]
        st.subheader("8 · Final recommendation (customer view)")
        if final:
            tp = final["top_pick"]
            st.success(f"🏆 **{tp['name']}** ({tp['brand']}) — {logic.fmt_inr(tp['price'])} · {tp['ram_gb']} GB RAM · "
                       f"{tp['storage_gb']} GB · ⭐ {tp['rating']} · score {tp['score']}")
            st.markdown("**Why:** " + "; ".join(final["reasoning"]))
            if final["alternatives"]:
                st.markdown("**Alternatives:** " + " · ".join(f"#{a['rank']} {a['name']} ({logic.fmt_inr(a['price'])})" for a in final["alternatives"]))
            st.caption(f"Validated: {final['validation_passed']} · Approved by {final['approved_by']} at {final['approved_at']}")
        else:
            st.info("Not published yet — a human decision is required (see **✅ Human Approval** tab).")

# ------------------------------------------------------------ Human approval
with tabs[1]:
    st.subheader("Human-in-the-loop approval gate")
    if wf is None:
        st.info("Run the pipeline first.")
    else:
        snap = wf.snapshot()
        decision = snap["supervisor_decision"] or {}
        status_banner(snap["status"], decision.get("summary", ""))
        if snap["human_approval"]:
            ha = snap["human_approval"]
            st.markdown(f"Decision recorded: **{ha['decision']}** by **{ha['reviewer']}** at {ha['timestamp']}")
            if ha["comment"]:
                st.markdown(f"> {ha['comment']}")
        elif snap["status"] == "BLOCKED_SECURITY":
            st.error("Security-blocked workflows cannot be approved or re-analysed. Start a new run.")
            with st.form("reject_blocked"):
                reviewer = st.text_input("Reviewer name", "Lab Reviewer")
                if st.form_submit_button("Acknowledge & reject"):
                    apply_human_decision(wf, "reject", reviewer, "Blocked by integrity violation")
                    st.rerun()
        else:
            if snap["ranking"]:
                st.markdown("**Proposed ranking for review**")
                show_table([{"Rank": r["rank"], "ID": r["product_id"], "Product": r["name"], "Price": logic.fmt_inr(r["price"]),
                             "Rating": r["rating"], "Score": r["score"]} for r in snap["ranking"]])
            for r in decision.get("escalation_reasons", []):
                st.markdown(f"- {r}")
            options = (["Approve"] if decision.get("approval_allowed") else []) + ["Reject", "Request re-analysis"]
            req = snap["requirements"] or {}
            with st.form("approval_form"):
                choice = st.radio("Decision", options, horizontal=True)
                reviewer = st.text_input("Reviewer name", "Lab Reviewer", max_chars=60)
                comment = st.text_area("Comment / reasoning review", max_chars=500)
                st.markdown("**For re-analysis** (optional)")
                excluded = st.multiselect("Flag products with incorrect information (exclude)",
                                          [r["product_id"] for r in snap["ranking"]],
                                          format_func=lambda pid: f"{pid} · {next((r['name'] for r in snap['ranking'] if r['product_id'] == pid), pid)}")
                use_over = st.checkbox("Apply requirement overrides (authorized human change)")
                o = st.columns(5)
                cat = o[0].selectbox("Category", data.SUPPORTED_CATEGORIES,
                                     index=data.SUPPORTED_CATEGORIES.index(req["category"]) if req.get("category") in data.SUPPORTED_CATEGORIES else 0)
                budget = o[1].number_input("Max budget ₹ (0 = none)", 0, 5_000_000, int(req.get("max_price") or 0), step=1000)
                ram = o[2].number_input("Min RAM GB (0 = none)", 0, 128, int(req.get("min_ram_gb") or 0))
                sto = o[3].number_input("Min storage GB (0 = none)", 0, 8192, int(req.get("min_storage_gb") or 0), step=64)
                rat = o[4].number_input("Min rating (0 = none)", 0.0, 5.0, float(req.get("min_rating") or 0.0), step=0.1)
                submitted = st.form_submit_button("Submit decision", type="primary")
            if submitted:
                overrides = None
                if use_over:
                    overrides = {"category": cat, "max_price": int(budget) or None, "min_ram_gb": int(ram) or None,
                                 "min_storage_gb": int(sto) or None, "min_rating": round(float(rat), 1) or None}
                action = {"Approve": "approve", "Reject": "reject", "Request re-analysis": "reanalyze"}[choice]
                try:
                    with st.spinner("Applying decision…"):
                        result = apply_human_decision(wf, action, reviewer, comment, excluded, overrides)
                    if result is not wf:
                        set_workflow(result)
                        ss.flash = f"Re-analysis started as {result.workflow_id}"
                    else:
                        ss.flash = f"Decision recorded: {action.upper()}"
                    st.rerun()
                except (InvalidInputError, AgentSystemError) as e:
                    st.error(str(e))

# ------------------------------------------------------------------- Trace
with tabs[2]:
    if wf is None:
        st.info("Run the pipeline first.")
    else:
        snap = wf.snapshot()
        st.subheader("Agent execution trace")
        trace_rows = [{"Step": t["step"], "Task": t["task_id"], "Agent": t["agent"], "Task description": t["task"],
                       "Start": t["start"], "End": t["end"], "Duration (ms)": t["duration_ms"], "Status": t["status"],
                       "Tools": ", ".join(t["tools"]), "Attempt": t["attempt"], "Error": t["error"] or "",
                       "Output status": t["output_status"]} for t in snap["trace"]]
        show_table(trace_rows)
        tl = pd.DataFrame([{"Agent": t["agent"], "Task": t["task_id"], "start": t["t_start_ms"],
                            "end": max(t["t_end_ms"], t["t_start_ms"] + 1), "Status": t["status"]} for t in snap["trace"]])
        if not tl.empty:
            st.markdown("**Timeline** (overlapping bars = parallel execution)")
            st.altair_chart(alt.Chart(tl).mark_bar(cornerRadius=3).encode(
                x=alt.X("start:Q", title="ms since workflow start"), x2="end:Q",
                y=alt.Y("Agent:N", sort=None), color=alt.Color("Status:N", scale=alt.Scale(
                    domain=["SUCCESS", "RETRYING", "FAILED", "SKIPPED"], range=["#4caf50", "#ff9800", "#e53935", "#9e9e9e"])),
                tooltip=["Agent", "Task", "Status", "start", "end"]).properties(height=320), width="stretch")
        st.subheader("Inter-agent communication (structured messages)")
        show_table([{"t (ms)": mm["t_ms"], "From": mm["sender"], "To": mm["receiver"], "Task": mm["task"],
                     "Input": mm["input"], "Output": mm["output"], "Status": mm["status"]} for mm in snap["messages"]])
        a, b = st.columns(2)
        with a:
            st.subheader("Tool usage log")
            show_table(snap["tool_log"])
        with b:
            st.subheader("Errors & warnings")
            show_table(snap["errors"])
            st.subheader("Security events")
            show_table(snap["security_events"])
        st.subheader("Shared workflow state")
        with st.expander("Inspect raw shared state (operator view)"):
            st.json({k: v for k, v in snap.items() if k not in ("trace", "messages", "tool_log")}, expanded=False)
        d1, d2 = st.columns(2)
        d1.download_button("⬇ Download state + trace (JSON)", json.dumps(snap, indent=2, default=str, ensure_ascii=False),
                           file_name=f"{snap['workflow_id']}.json", mime="application/json")
        if LOG_FILE.exists():
            lines = [ln for ln in LOG_FILE.read_text(encoding="utf-8").splitlines() if snap["workflow_id"] in ln]
            d2.download_button(f"⬇ Download structured log ({len(lines)} events)", "\n".join(lines),
                               file_name=f"{snap['workflow_id']}.log.jsonl", mime="application/json")

# ------------------------------------------------------------- Performance
with tabs[3]:
    st.subheader("Sequential vs parallel execution")
    st.markdown("**Speedup = Sequential Time / Parallel Time**. The three Search Agents are independent, so the Router "
                "schedules them concurrently; all dependent stages stay sequential.")
    p1, p2, p3 = st.columns(3)
    pq = p1.text_input("Query", ss.query, key="perf_query")
    plat = p2.slider("Catalog latency (s)", 0.05, 1.0, 0.3, 0.05, key="perf_lat")
    pruns = p3.slider("Runs per mode", 1, 5, 3, key="perf_runs")
    if st.button("Run performance comparison", type="primary"):
        try:
            with st.spinner("Benchmarking…"):
                ss.perf = run_performance_comparison(pq, plat, pruns)
        except InvalidInputError as e:
            st.error(str(e))
    if ss.perf:
        s = ss.perf["summary"]
        c = st.columns(5)
        c[0].metric("Sequential (avg)", f"{s['sequential_total_s']:.3f} s")
        c[1].metric("Parallel (avg)", f"{s['parallel_total_s']:.3f} s")
        c[2].metric("Speedup (total)", f"{s['speedup_total']}×")
        c[3].metric("Speedup (search stage)", f"{s['speedup_search_stage']}×")
        c[4].metric("Same recommendation?", "Yes" if s["same_result"] else "No")
        runs = pd.DataFrame(ss.perf["runs"])
        st.dataframe(runs, hide_index=True)
        avg = runs.groupby("Mode", as_index=False)[["Total time (s)", "Search stage (s)"]].mean().melt("Mode", var_name="Metric", value_name="Seconds")
        st.altair_chart(alt.Chart(avg).mark_bar().encode(x=alt.X("Mode:N", title=None), y="Seconds:Q", color="Mode:N",
                                                         column=alt.Column("Metric:N", title=None)).properties(width=220, height=260))
        st.caption("Agent executions and tool calls are identical in both modes — parallelism reduces waiting, not work.")
    st.subheader("Experimental cost model")
    show_table([{"Component": k, "Units per occurrence": v} for k, v in COST_WEIGHTS.items()])
    if wf is not None:
        m = wf.read("metrics")
        st.markdown(f"Current workflow cost: **{m.get('cost_units')} units** → {m.get('cost_breakdown')}")

# --------------------------------------------------------------- Security
with tabs[4]:
    st.subheader("Security validation suite")
    st.markdown("Prompt injection, unauthorized tool access, shared-state manipulation, requirement manipulation, "
                "direct tampering, forged approvals, malformed input.")
    if st.button("Run security tests", type="primary"):
        with st.spinner("Attacking the pipeline…"):
            ss.security = run_security_tests()
    if ss.security:
        passed = sum(r["Result"] == "PASS" for r in ss.security)
        (st.success if passed == len(ss.security) else st.error)(f"{passed}/{len(ss.security)} security tests passed")
        st.dataframe(result_style(to_df(ss.security)), hide_index=True)
    st.subheader("Shared-state write permissions (least privilege)")
    show_table([{"Field": f, "Writable by": ", ".join(sorted(a))} for f, a in WRITE_PERMISSIONS.items()])

# --------------------------------------------------------------- Testing
with tabs[5]:
    a, b = st.columns(2)
    with a:
        st.subheader("Functional testing")
        if st.button("Run functional tests", type="primary"):
            with st.spinner("Running…"):
                ss.functional = run_functional_tests()
    with b:
        st.subheader("Failure testing")
        if st.button("Run failure tests", type="primary"):
            with st.spinner("Injecting faults…"):
                ss.failure = run_failure_tests()
    for key, label in (("functional", "Functional"), ("failure", "Failure")):
        rows = ss[key]
        if rows:
            passed = sum(r["Result"] == "PASS" for r in rows)
            (st.success if passed == len(rows) else st.error)(f"{label}: {passed}/{len(rows)} passed")
            st.dataframe(result_style(to_df(rows)), hide_index=True)

# ------------------------------------------------------------------ Tools
with tabs[6]:
    st.subheader("Basic MCP-style tool registry")
    st.info("Simplified, in-process interface demonstrating registration, discovery, selection, controlled execution and "
            "authorization. It is **not** the full MCP protocol (covered in Experiment 06).")
    sandbox = WorkflowState("tool registry sandbox")
    reg = build_registry(sandbox, FailureInjector(), 0.0, 1.0)
    with st.expander("tools/list — registered tool descriptors", expanded=False):
        st.json(reg.list_tools(), expanded=False)
    st.markdown("**Permission matrix**")
    st.dataframe(pd.DataFrame(reg.permission_matrix(AGENT_NAMES)), hide_index=True)
    st.markdown("**Discovery & controlled execution playground**")
    c1, c2 = st.columns(2)
    agent = c1.selectbox("Calling agent", AGENT_NAMES)
    c1.markdown("Tools discovered: " + (", ".join(f"`{t['name']}`" for t in reg.discover(agent)) or "none (planning/routing only)"))
    tool = c2.selectbox("Tool to call", [t["name"] for t in reg.list_tools()] + ["delete_catalog (unregistered)"])
    if c2.button("tools/call"):
        name = tool.split(" ")[0]
        sample_args = {
            "query_parser": {"query": DEFAULT_QUERY},
            "product_search": {"source": "A", "category": "laptop"},
            "synchronize_results": {"results_by_source": {"A": data.get_source_catalog("A")[:2]}},
            "filter_products": {"products": data.get_source_catalog("A")[:3], "requirements": logic.parse_query(DEFAULT_QUERY)["requirements"]},
            "compare_products": {"products": [], "requirements": logic.parse_query(DEFAULT_QUERY)["requirements"]},
            "score_products": {"products": [], "requirements": logic.parse_query(DEFAULT_QUERY)["requirements"]},
            "validate_requirements": {"requirements": logic.parse_query(DEFAULT_QUERY)["requirements"]},
            "validate_filtered": {"filtered": [], "requirements": logic.parse_query(DEFAULT_QUERY)["requirements"]},
            "validate_recommendation": {"ranking": [], "filtered": [], "requirements": logic.parse_query(DEFAULT_QUERY)["requirements"], "integrity_ok": True},
        }.get(name, {})
        try:
            out = reg.call(agent, name, **sample_args)
            st.success(f"✅ {agent} executed `{name}`")
            st.json(out if isinstance(out, (dict, list)) else {"result": str(out)}, expanded=False)
        except AgentSystemError as e:
            st.error(f"⛔ {type(e).__name__}: {e}")
        show_table(sandbox.read("tool_log"))
        show_table(sandbox.read("security_events"))

# ------------------------------------------------------------ Observation
with tabs[7]:
    st.subheader("Observation table")
    if wf is None:
        st.info("Run the pipeline (and optionally the performance and security suites) to fill the table.")
    else:
        obs = build_observation_table(wf, ss.perf, ss.security)
        st.dataframe(pd.DataFrame(obs), hide_index=True)
        if not ss.perf or not ss.security:
            st.caption("Tip: run **⚡ Performance** and **🛡️ Security Tests** to complete every row.")
        buf = io.StringIO()
        pd.DataFrame(obs).to_csv(buf, index=False)
        md = "| Parameter | Observation |\n|---|---|\n" + "\n".join(
            f"| {r['Parameter']} | {str(r['Observation']).replace('|', '/')} |" for r in obs)
        c1, c2 = st.columns(2)
        c1.download_button("⬇ CSV", buf.getvalue(), file_name="observation_table.csv", mime="text/csv")
        c2.download_button("⬇ Markdown", md, file_name="observation_table.md", mime="text/markdown")
    st.subheader("Result")
    st.markdown("The multi-agent e-commerce product analysis and recommendation pipeline was implemented using specialized "
                "agents for planning, routing, searching, filtering, comparison, ranking, validation and supervision. It "
                "demonstrates coordination, shared workflow state, inter-agent communication, sequential and parallel "
                "execution, synchronization, human-in-the-loop approval, failure handling with controlled retry, logging, "
                "tracing, security validation, performance and cost measurement, and basic MCP-style tool integration.")
    st.subheader("Conclusion")
    st.markdown("A complex recommendation request was transformed into a coordinated, dependency-aware multi-agent workflow. "
                "Specialization with least-privilege tools made each step explainable and auditable; validated shared state "
                "and checkpoint validation prevented invalid or manipulated results; parallel search reduced latency without "
                "changing the outcome; and the human approval gate added governance before publication.")

# ----------------------------------------------------------- Architecture
with tabs[8]:
    st.subheader("System architecture")
    st.graphviz_chart(ARCH_DOT, width="stretch")
    st.subheader("Agents and responsibilities")
    tmp_reg = build_registry(WorkflowState("arch"), FailureInjector(), 0.0, 1.0)
    show_table([{"Agent": a, "Responsibility": AGENT_RESPONSIBILITIES[a],
                 "Tools": ", ".join(t["name"] for t in tmp_reg.discover(a)) or "— (internal logic only)"} for a in AGENT_NAMES])
    st.subheader("Catalog sources (trust priority for conflict resolution)")
    show_table([{"Source": k, "Name": v["name"], "Trust priority": v["trust_priority"],
                 "Listings": len(data.get_source_catalog(k))} for k, v in data.SOURCES.items()])
    st.subheader("Optimization evaluation")
    show_table([
        {"Parameter": "Execution", "Basic": "Sequential", "Optimized (implemented)": "Parallel Search Agents via thread pool + barrier"},
        {"Parameter": "Communication", "Basi2c": "Unstructured", "Optimized (implemented)": "Structured messages: sender, receiver, task, input, output, status"},
        {"Parameter": "State management", "Basic": "Basic shared state", "Optimized (implemented)": "Role-based writes, write-once fields, SHA-256 integrity hash"},
        {"Parameter": "Routing", "Basic": "Fixed", "Optimized (implemented)": "Topological levels from task dependencies"},
        {"Parameter": "Tool access", "Basic": "Broad", "Optimized (implemented)": "Per-tool allow-lists, schema validation, denial logging"},
        {"Parameter": "Retry", "Basic": "Repeated", "Optimized (implemented)": "Recoverable-only, bounded (≤5), linear backoff"},
        {"Parameter": "Validation", "Basic": "Final only", "Optimized (implemented)": "Checkpoints: decomposition, filtering, final"},
        {"Parameter": "Ranking", "Basic": "Basic scoring", "Optimized (implemented)": "Requirement-aware weights, per-factor contributions, reasons"},
        {"Parameter": "Logging", "Basic": "Basic", "Optimized (implemented)": "JSON-lines log + per-step trace with timings"},
        {"Parameter": "Cost", "Basic": "Duplicate calls", "Optimized (implemented)": "Search cache reused on re-analysis; no duplicate searches"},
    ])

# ---------------------------------------------------------------- History
with tabs[9]:
    st.subheader("Workflows in this session")
    if not ss.history:
        st.caption("— none —")
    else:
        show_table([{"Workflow": h.workflow_id, "Parent": h.read("parent_workflow_id") or "", "Query": h.read("user_query"),
                     "Mode": h.read("mode"), "Status": h.status,
                     "Top pick": (h.read("ranking") or [{}])[0].get("name", "—"),
                     "Time (s)": h.read("metrics").get("total_time_s"),
                     "Cache hits": h.read("metrics")["tool_cache_hits"]} for h in reversed(ss.history)])
        if st.button("Clear history"):
            ss.history, ss.wf = [], None
            st.rerun()
