import os
import sys
from decimal import Decimal
import pandas as pd
import streamlit as st

from recruitment.config import (
    DEFAULT_DATA_PATH,
    DEFAULT_RULES_PATH,
    DEFAULT_OUTPUTS_DIR,
    get_output_paths,
    ROLES,
    ROLE_HR_REVIEWER,
    ROLE_VIEWER,
    ACTIONS,
    APPROVE,
    EDIT,
    HOLD,
    REQUEST_INFO,
    ROUTING_STATUSES,
    SHORTLIST_REVIEW,
    MANUAL_REVIEW,
    NOT_SHORTLISTED_REVIEW,
    REVIEW_PENDING,
)
from recruitment.pipeline_graph import run_pipeline, load_pipeline_results
from recruitment.review_graph import run_review, load_review_decisions
from recruitment.drafts import polish_draft
from recruitment.audit import read_audit_log
from recruitment.metrics import (
    metrics_from_outputs,
    format_metrics,
    run_test_suite,
    compute_metrics,
)
from recruitment.scoring import format_score

st.set_page_config(page_title="Recruitment Workflow", layout="wide")

# CSS to style badges and clean UI
st.markdown(
    """
    <style>
    .metric-badge {
        display: inline-block;
        padding: 4px 8px;
        background-color: #222;
        color: #fff;
        border-radius: 4px;
        font-size: 11px;
        font-weight: bold;
        letter-spacing: 1px;
    }
    .big-score {
        font-size: 52px;
        font-weight: 800;
        line-height: 1;
        margin-bottom: 0px;
    }
    .small-score {
        font-size: 18px;
        color: #888;
        font-weight: normal;
    }
    .denied-banner {
        background-color: #000000;
        color: #ffffff;
        padding: 12px 18px;
        border-radius: 4px;
        font-weight: bold;
        margin-bottom: 20px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------- SIDEBAR: SESSION -----------------
st.sidebar.title("Session")
reviewer_id = st.sidebar.text_input("REVIEWER ID", value="HR-001")
role = st.sidebar.selectbox("ROLE", options=ROLES, index=ROLES.index(ROLE_HR_REVIEWER) if ROLE_HR_REVIEWER in ROLES else 0)

# Rules selector
rules_options = ["rules.json"]
rules_file = st.sidebar.selectbox("RULES", options=rules_options, index=0)
rules_path = DEFAULT_RULES_PATH

# Gemini API Key input
gemini_api_key = st.sidebar.text_input(
    "GEMINI API KEY",
    value=os.environ.get("GEMINI_API_KEY", ""),
    type="password",
    help="Optional: Used to polish draft notifications in the Review tab.",
)

simulate_failure = st.sidebar.checkbox("SIMULATE DELIVERY FAILURE", value=False)

# Session state initialization
if "test_results" not in st.session_state:
    st.session_state["test_results"] = None
if "last_action_message" not in st.session_state:
    st.session_state["last_action_message"] = None

# Ensure pipeline output exists
try:
    pipeline_data = load_pipeline_results(DEFAULT_OUTPUTS_DIR)
except Exception:
    pipeline_data = run_pipeline(DEFAULT_DATA_PATH, rules_path, DEFAULT_OUTPUTS_DIR, reset=False)

# ----------------- MAIN TITLE & TABS -----------------
st.title("Recruitment Workflow")

tab_pipeline, tab_review, tab_audit, tab_metrics = st.tabs(["Pipeline", "Review", "Audit", "Metrics"])

# ==============================================================================
# TAB 1: PIPELINE
# ==============================================================================
with tab_pipeline:
    col_run1, col_run2 = st.columns([1, 4])
    with col_run1:
        if st.button("Run Pipeline (Fresh)", use_container_width=True):
            with st.spinner("Executing Pipeline Graph..."):
                pipeline_data = run_pipeline(DEFAULT_DATA_PATH, rules_path, DEFAULT_OUTPUTS_DIR, reset=True)
                st.session_state["last_action_message"] = None
                st.success("Pipeline executed successfully!")
                st.rerun()

    results = pipeline_data.get("results", [])
    rejected = pipeline_data.get("rejected", [])

    # Load latest review decisions to show status in table
    decisions = load_review_decisions(DEFAULT_OUTPUTS_DIR, latest_only=True)
    decision_map = {d["candidate_id"]: d["review_status"] for d in decisions}

    # Queue filter
    queue_filter = st.selectbox(
        "Queue Filter",
        options=["All", SHORTLIST_REVIEW, MANUAL_REVIEW, NOT_SHORTLISTED_REVIEW],
        index=0,
        key="pipeline_queue_filter",
    )

    table_rows = []
    for r in results:
        prop = r.get("proposed_status", "")
        if queue_filter != "All" and prop != queue_filter:
            continue
        cid = r.get("candidate_id", "")
        rev = decision_map.get(cid, REVIEW_PENDING)
        table_rows.append({
            "ID": cid,
            "Name": r.get("name", ""),
            "Skills": int(r.get("skills_score", 0)),
            "Experience": int(r.get("experience_score", 0)),
            "Assessment": int(r.get("assessment_score", 0)),
            "Score": float(r.get("score", 0)),
            "Proposed": prop,
            "Review": rev,
        })

    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, height=350)

    st.subheader("Quarantined")
    if rejected:
        rej_rows = [{"Row": r["row"], "ID": r["candidate_id"], "Reason": r["reason"]} for r in rejected]
        st.dataframe(pd.DataFrame(rej_rows), use_container_width=True)
    else:
        st.info("No quarantined records.")

# ==============================================================================
# TAB 2: REVIEW
# ==============================================================================
with tab_review:
    if st.session_state["last_action_message"]:
        msg_type, msg_text = st.session_state["last_action_message"]
        if msg_type == "denied":
            st.markdown(f'<div class="denied-banner">{msg_text}</div>', unsafe_allow_html=True)
        elif msg_type == "success":
            st.success(msg_text)
        elif msg_type == "error":
            st.error(msg_text)

    # Queue and Candidate Selectors
    c_col1, c_col2 = st.columns([1, 2])
    with c_col1:
        rev_queue = st.selectbox(
            "QUEUE",
            options=["All", SHORTLIST_REVIEW, MANUAL_REVIEW, NOT_SHORTLISTED_REVIEW],
            index=0,
            key="rev_queue_select",
        )

    filtered_candidates = [
        c for c in results
        if rev_queue == "All" or c.get("proposed_status") == rev_queue
    ]

    candidate_options = [
        f"{c['candidate_id']} · {c['name']} · {format_score(c['score'])}"
        for c in filtered_candidates
    ]

    selected_cand = None
    with c_col2:
        if candidate_options:
            selected_label = st.selectbox("CANDIDATE", options=candidate_options, key="cand_select")
            sel_cid = selected_label.split(" · ")[0]
            selected_cand = next((c for c in filtered_candidates if c["candidate_id"] == sel_cid), None)
        else:
            st.selectbox("CANDIDATE", options=["No candidates in this queue"])

    if selected_cand:
        cid = selected_cand["candidate_id"]
        c_left, c_right = st.columns([1.1, 1.2])

        # LEFT: Score, breakdown, decision
        with c_left:
            st.markdown(
                f'<div class="big-score">{int(selected_cand["score"])}<span class="small-score">/100</span></div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<span class="metric-badge">{selected_cand["proposed_status"]}</span> &nbsp; <span style="color:#777; font-size:12px;">rules {selected_cand.get("rule_version", "v1.0")}</span>',
                unsafe_allow_html=True,
            )
            st.write("")

            for b in selected_cand.get("breakdown", []):
                label = b.get("label", b.get("criterion"))
                inp = int(b.get("input", 0))
                weight = int(b.get("weight", 0))
                contrib = float(b.get("contribution", 0))
                max_contrib = weight
                progress_val = min(max(contrib / max_contrib, 0.0), 1.0) if max_contrib else 0
                
                col_b1, col_b2 = st.columns([3, 1])
                with col_b1:
                    st.caption(f"{label} · input {inp}")
                with col_b2:
                    st.markdown(f"<div style='text-align:right; font-size:12px; font-weight:600;'>{contrib:g} / {weight}</div>", unsafe_allow_html=True)
                st.progress(progress_val)

            st.markdown("### Decision")
            action_choice = st.radio("ACTION", options=ACTIONS, horizontal=True)

            override_status = None
            override_reason = ""
            if action_choice == EDIT:
                e_col1, e_col2 = st.columns([1, 1.5])
                with e_col1:
                    override_status = st.selectbox("OVERRIDE STATUS", options=ROUTING_STATUSES, index=ROUTING_STATUSES.index(selected_cand["proposed_status"]))
                with e_col2:
                    override_reason = st.text_input("REASON", value="Strong open-source contributions")

            notes = st.text_area("NOTES", height=68)

            if st.button("Submit decision", type="primary"):
                # Get potentially edited draft from session state
                draft_to_use = {
                    "subject": st.session_state.get(f"draft_subj_{cid}", selected_cand["draft"]["subject"]),
                    "message": st.session_state.get(f"draft_msg_{cid}", selected_cand["draft"]["message"]),
                }
                
                review_out = run_review(
                    candidate_id=cid,
                    reviewer_id=reviewer_id,
                    role=role,
                    action=action_choice,
                    override_status=override_status,
                    reason=override_reason,
                    notes=notes,
                    draft=draft_to_use,
                    simulate_failure=simulate_failure,
                    outputs_dir=DEFAULT_OUTPUTS_DIR,
                )

                if review_out["blocked"]:
                    if review_out["block_event"] == "ACCESS_DENIED":
                        st.session_state["last_action_message"] = ("denied", review_out["block_reason"])
                    else:
                        st.session_state["last_action_message"] = ("error", review_out["block_reason"])
                else:
                    st.session_state["last_action_message"] = (
                        "success",
                        f"Decision recorded: {review_out['review_status']} | Notification: {review_out['notification_status']}"
                    )
                st.rerun()

        # RIGHT: Draft preview & Polish
        with c_right:
            st.markdown("### Draft <span class='metric-badge' style='background:#555;'>DRAFT</span>", unsafe_allow_html=True)
            
            draft_obj = selected_cand.get("draft", {})
            draft_key = f"draft_msg_{cid}"
            subj_key = f"draft_subj_{cid}"

            if draft_key not in st.session_state:
                st.session_state[draft_key] = draft_obj.get("message", "")
            if subj_key not in st.session_state:
                st.session_state[subj_key] = draft_obj.get("subject", "")

            subj_val = st.text_input("SUBJECT", value=st.session_state[subj_key], key=f"inp_{subj_key}")
            msg_val = st.text_area("MESSAGE", value=st.session_state[draft_key], height=240, key=f"inp_{draft_key}")
            st.session_state[subj_key] = subj_val
            st.session_state[draft_key] = msg_val

            if st.button("Polish with Gemini"):
                curr_draft = {
                    "subject": st.session_state[subj_key],
                    "message": st.session_state[draft_key],
                    "candidate_id": cid,
                }
                api_key_to_use = gemini_api_key.strip() if gemini_api_key else None
                polished = polish_draft(curr_draft, selected_cand, api_key=api_key_to_use)
                if polished.get("polish_status") == "POLISHED":
                    st.session_state[draft_key] = polished["message"]
                    st.success("Draft successfully polished!")
                    st.rerun()
                else:
                    st.warning(f"Fallback to template: {polished.get('polish_reason', 'Unknown reason')}")

# ==============================================================================
# TAB 3: AUDIT
# ==============================================================================
with tab_audit:
    audit_records = read_audit_log(get_output_paths(DEFAULT_OUTPUTS_DIR).audit)
    if audit_records:
        df_audit = pd.DataFrame(audit_records)
        all_events = sorted(list(df_audit["event"].unique()))
        selected_events = st.multiselect("EVENT", options=all_events, default=[])

        if selected_events:
            df_filtered = df_audit[df_audit["event"].isin(selected_events)]
        else:
            df_filtered = df_audit

        st.dataframe(df_filtered, use_container_width=True, height=450)

        csv_bytes = df_audit.to_csv(index=False).encode("utf-8")
        st.download_button("Download audit_log.csv", data=csv_bytes, file_name="audit_log.csv", mime="text/csv")
    else:
        st.info("No audit logs recorded yet.")

# ==============================================================================
# TAB 4: METRICS
# ==============================================================================
with tab_metrics:
    col_t1, col_t2 = st.columns([1, 4])
    with col_t1:
        if st.button("Run tests", use_container_width=True):
            with st.spinner("Running 50 pytest tests..."):
                passed, total = run_test_suite()
                st.session_state["test_results"] = (passed, total)
                st.rerun()

    m = metrics_from_outputs(DEFAULT_OUTPUTS_DIR, test_results=st.session_state["test_results"])

    # KPI Top cards
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("VALIDATION RATE", f"{m['data_validation_rate']:.1f}%")
    k2.metric("WORKFLOW SUCCESS", f"{m['workflow_success_rate']:.1f}%")
    k3.metric("DRAFT GENERATION", f"{m['draft_generation_rate']:.1f}%")
    test_str = f"{m['test_pass_rate']:.1f}%" if m['test_pass_rate'] is not None else "Not run"
    k4.metric("TEST PASS RATE", test_str)
    k5.metric("AVG TIME / RECORD", f"{m['avg_processing_ms']:.3f} ms")
    k6.metric("REVIEW COMPLETION", f"{m['human_review_completion_rate']:.1f}%")

    st.write("---")

    # Detailed Table
    table_data = format_metrics(m)
    df_metrics = pd.DataFrame(table_data, columns=["PARAMETER", "OBSERVATION"])
    st.dataframe(df_metrics, use_container_width=True, height=480)

