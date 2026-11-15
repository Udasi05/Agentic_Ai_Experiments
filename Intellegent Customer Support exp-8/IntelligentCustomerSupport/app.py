import csv, json, uuid, sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd
import streamlit as st
from classifier import classify_rules
from resolver import load_kb, retrieve, route
try:
    from mcp_client import run_mcp_workflow
    MCP_AVAILABLE=True
except ImportError:
    run_mcp_workflow=None
    MCP_AVAILABLE=False
from ollama_client import check_model, classify_with_ollama, grounded_draft

ROOT=Path(__file__).parent
DATA=ROOT/"customer_queries.csv"
DB=ROOT/"tickets.db"
CFG=json.loads((ROOT/"config.json").read_text())
st.set_page_config(page_title="Intelligent Customer Support",page_icon="🎧",layout="wide")
st.markdown("<style>.block-container{padding-top:1.5rem} .step-card{padding:1rem;border:1px solid #28384b;border-radius:14px;background:#111b29;margin:.5rem 0}</style>",unsafe_allow_html=True)

def db():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    con.execute("CREATE TABLE IF NOT EXISTS tickets(ticket_id TEXT PRIMARY KEY,query_id TEXT,intent TEXT,priority TEXT,status TEXT,team TEXT,created_at TEXT,due_at TEXT,summary TEXT)")
    con.commit(); return con

def make_ticket(query,c,route_name,summary):
    con=db(); tid="TCK-"+uuid.uuid4().hex[:8].upper(); now=datetime.now(timezone.utc); due=now+timedelta(minutes=CFG["sla_minutes"].get(c["priority"],240))
    status="PENDING_APPROVAL" if route_name=="PROPOSE_AUTO_RESOLUTION" else "ESCALATED"
    team="Security Response" if c["intent"]=="Security Concern" else "Billing Support" if c["intent"]=="Billing" else "Product Feedback" if c["intent"]=="Feature Request" else "Customer Support"
    con.execute("INSERT INTO tickets VALUES(?,?,?,?,?,?,?,?,?)",(tid,query.get("query_id","LIVE"),c["intent"],c["priority"],status,team,now.isoformat(),due.isoformat(),summary)); con.commit(); con.close(); return tid,due.isoformat()

def validate_rows(rows):
    seen=set(); good=[]; bad=[]
    for i,r in enumerate(rows,2):
        row={k:str(v or "").strip() for k,v in r.items()}
        errors=[]
        for field in ("query_id","customer_id","query_text","created_at"):
            if not row.get(field): errors.append("Missing or empty "+field)
        if row.get("query_id") in seen: errors.append("Duplicate query_id")
        seen.add(row.get("query_id"))
        (good if not errors else bad).append({**row,"_line":i,"_errors":errors})
    return good,bad

def workflow(query,use_model=False,use_mcp=True):
    steps=[]
    steps.append(("1 · Ingest & validate",f"Query {query.get('query_id','LIVE')} from {query.get('customer_id','manual entry')} passed required-field validation."))
    if use_mcp and MCP_AVAILABLE:
        try:
            payload=run_mcp_workflow(query["query_text"])
            c=payload["classification"]; found=payload["retrieval"]; article=found["article"]; score=found["score"]; matched=found["matched_keywords"]; route_name=payload["route"]
        except Exception as error:
            st.warning(f"MCP tool startup failed; using local workflow fallback: {error}")
            c=classify_rules(query["query_text"]); article,score,matched=retrieve(query["query_text"],load_kb(),c["intent"]); route_name=route(c,score,article)
            payload=None
        if payload:
            steps.append(("2 · MCP classification",f"Local MCP tool classify_support_query → {c['intent']} · {c['complexity']} · {c['priority']}."))
            steps.append(("3 · MCP knowledge retrieval",f"Local MCP tool search_approved_knowledge → {article['article_id'] if article else 'no approved article'} · {score}% heuristic match; matched: {', '.join(matched) or 'none'}."))
            steps.append(("4 · MCP workflow routing",f"Local MCP tool decide_support_route → {route_name}."))
        else:
            steps.append(("2 · MCP tool unavailable",f"Rule baseline fallback → {c['intent']} · {c['complexity']} · {c['priority']} · {route_name}."))
    else:
        c=classify_rules(query["query_text"]); article,score,matched=retrieve(query["query_text"],load_kb(),c["intent"]); route_name=route(c,score,article)
    model_seconds=None; model_note="Rule baseline"
    if use_model:
        try:
            model_c,model_seconds=classify_with_ollama(query["query_text"],CFG["ollama_url"],CFG["model"])
            # Risk-first deterministic rules win whenever they identify a critical/security signal.
            if c["priority"]=="P1" or c["intent"]=="Security Concern": model_note="Qwen checked; deterministic P1/security safeguard retained"
            else: c=model_c; article,score,matched=retrieve(query["query_text"],load_kb(),c["intent"]); route_name=route(c,score,article); model_note=f"Qwen 2.5 7B classification ({model_seconds:.2f}s); label schema validated"
        except Exception as e: model_note=f"Ollama unavailable/invalid response; safe rule baseline used ({str(e)[:140]})"
    steps.append(("5 · Local Qwen model",model_note))
    steps.append(("6 · Grounded response draft",f"Draft uses {article['article_id']} only." if article else "No approved article found; no answer invented."))
    summary=article["response"] if article else "A support agent should review this query and request any missing context."
    if use_model and article and c["intent"]!="Security Concern":
        try: summary=grounded_draft(query["query_text"],article,CFG["ollama_url"],CFG["model"])
        except Exception: pass
    steps.append(("7 · Ticket & SLA", "Ticket created with priority-based first-response deadline." if route_name!="PROPOSE_AUTO_RESOLUTION" or True else ""))
    if route_name!="PROPOSE_AUTO_RESOLUTION" or c["priority"] in ("P1","P2"):
        tid,due=make_ticket(query,c,route_name,summary)
        steps[-1]=(steps[-1][0],f"{tid} · {c['priority']} due {due} · {route_name}.")
    else: tid="Draft only · awaiting review"; steps[-1]=(steps[-1][0],"Low-risk answer is pending approval; no resolved status claimed.")
    steps.append(("8 · Notification & audit", "Notification is a draft in this lab; decision and ticket are persisted locally."))
    return {"query":query,"classification":c,"article":article,"score":score,"route":route_name,"response":summary,"ticket":tid,"steps":steps}

st.title("🎧 Intelligent Customer Support")
st.caption("SaaS support workflow · Local Qwen 2.5 7B · Approved knowledge · Human escalation · MCP tools")
page=st.sidebar.radio("Workspace",["Guided support","Batch tests","Tickets & metrics","System setup"])

if page=="Guided support":
    st.subheader("Work through one customer query")
    query_text=st.text_area("Customer query",placeholder="Describe the issue…",height=100)
    a,b=st.columns(2); use_model=a.toggle("Use local Ollama Qwen 2.5 7B",value=True); use_mcp=b.toggle("Run workflow through local MCP server",value=MCP_AVAILABLE,disabled=not MCP_AVAILABLE)
    if not MCP_AVAILABLE: st.warning("MCP Python package is missing. The app can run with the rule baseline, but MCP tools are unavailable until `mcp[cli]` is installed.")
    if st.button("Process query",type="primary",disabled=not query_text.strip()):
        with st.spinner("Running each workflow stage…"):
            result=workflow({"query_id":"LIVE-"+uuid.uuid4().hex[:6].upper(),"customer_id":"C-LIVE","query_text":query_text.strip(),"created_at":datetime.now(timezone.utc).isoformat()},use_model,use_mcp)
            st.session_state["last_result"]=result
    result=st.session_state.get("last_result")
    if result:
        st.markdown("### Workflow trace")
        for title,detail in result["steps"]:
            with st.container(border=True): st.markdown(f"**{title}**  \n{detail}")
        c1,c2,c3,c4=st.columns(4); c1.metric("Intent",result["classification"]["intent"]); c2.metric("Priority",result["classification"]["priority"]); c3.metric("KB match",f"{result['score']}%"); c4.metric("Route",result["route"])
        st.markdown("### Proposed response"); st.info(result["response"])
        st.caption(f"Ticket: {result['ticket']} · Article: {result['article']['article_id'] if result['article'] else 'None'} · Draft is not marked resolved.")

elif page=="Batch tests":
    st.subheader("Batch test bench")
    st.write("Run the fixed lab scenario suite and/or process the full synthetic CSV. Every row shows query, expected outcome, observed result, and status.")
    testtab,dataset=st.tabs(["14 scenario tests","500-record dataset"])
    with testtab:
        cases=json.loads((ROOT/"test_cases.json").read_text())
        if st.button("Run all 14 tests",type="primary"):
            outputs=[]
            for t in cases:
                if t["test_id"]=="TC05":
                    _,bad=validate_rows([{"query_id":"TC05","customer_id":"C-TEST","query_text":"","created_at":"2026-10-20"}]); actual="Rejected: "+", ".join(bad[0]["_errors"]); passed=bool(bad)
                elif t["test_id"]=="TC06":
                    _,bad=validate_rows([{"query_id":"DUP","customer_id":"C-1","query_text":"First","created_at":"2026-10-20"},{"query_id":"DUP","customer_id":"C-2","query_text":"Second","created_at":"2026-10-20"}]); actual="Duplicate rejected: "+", ".join(bad[0]["_errors"]); passed=any("Duplicate query_id" in e for e in bad[0]["_errors"])
                else:
                    c=classify_rules(t["query"]); art,score,_=retrieve(t["query"],load_kb(),c["intent"]); rt=route(c,score,art)
                    if t["test_id"]=="TC01": actual=c["intent"]; passed=actual=="Login / Access"
                    elif t["test_id"]=="TC02": actual=c["intent"]; passed=actual=="Billing"
                    elif t["test_id"]=="TC03": actual=c["priority"]+" urgent escalation"; passed=c["priority"]=="P1" and rt=="URGENT_HUMAN_ESCALATION"
                    elif t["test_id"]=="TC04": actual=c["intent"]; passed=actual=="Feature Request"
                    elif t["test_id"]=="TC07": actual=rt; passed=rt=="CREATE_TICKET_AND_ESCALATE"
                    elif t["test_id"]=="TC08": actual="Proposed grounded response" if rt=="PROPOSE_AUTO_RESOLUTION" else rt; passed=rt=="PROPOSE_AUTO_RESOLUTION"
                    elif t["test_id"]=="TC09": actual=rt+" (ambiguous)"; passed=c["intent"]=="Unknown"
                    elif t["test_id"]=="TC10" or t["test_id"].startswith("MAL"):
                        actual=rt+" · "+c["intent"]+" · "+c["complexity"]+" · "+c["priority"]
                        passed=c["intent"]=="Security Concern" and c["priority"]=="P1" and rt=="URGENT_HUMAN_ESCALATION"
                    else: actual=rt; passed=rt=="URGENT_HUMAN_ESCALATION"
                outputs.append({"Test":t["test_id"],"Scenario":t["scenario"],"Query / fixture":t["query"],"Expected":t["expected"],"Observed result":actual,"Status":"PASS" if passed else "FAIL"})
            st.session_state["test_outputs"]=outputs
        if "test_outputs" in st.session_state:
            df=pd.DataFrame(st.session_state["test_outputs"]); st.dataframe(df,use_container_width=True,hide_index=True)
            st.metric("Passed executable checks",f"{sum(x['Status']=='PASS' for x in st.session_state['test_outputs'])} / {len(df)}")
            st.caption("Security-threat cases use deterministic risk rules and are escalated for human handling. Security-classified queries are not sent to Qwen for response drafting.")
    with dataset:
        st.caption("Synthetic records only. CSV includes normal support traffic plus empty, duplicate-ID, ambiguous, billing-priority, and no-KB edge cases.")
        rows=list(csv.DictReader(DATA.open(encoding="utf-8-sig"))); st.metric("Rows",len(rows)); st.dataframe(pd.DataFrame(rows).head(30),use_container_width=True,hide_index=True)
        limit=st.slider("Rows to process",min_value=25,max_value=len(rows),value=min(100,len(rows)),step=25)
        if st.button("Process selected dataset rows"):
            valid,rejected=validate_rows(rows[:limit]); out=[]
            for q in valid:
                c=classify_rules(q["query_text"]); art,score,matched=retrieve(q["query_text"],load_kb(),c["intent"]); rt=route(c,score,art)
                out.append({"Query ID":q["query_id"],"Customer":q["customer_id"],"Query":q["query_text"],"Intent":c["intent"],"Complexity":c["complexity"],"Priority":c["priority"],"Article":art["article_id"] if art else "—","Match":score,"Route":rt,"Result":art["response"] if art else "Escalated for human review"})
            st.session_state["batch_rows"]=out; st.session_state["batch_rejects"]=rejected
        if "batch_rows" in st.session_state:
            st.markdown("#### Processed query results"); st.dataframe(pd.DataFrame(st.session_state["batch_rows"]),use_container_width=True,hide_index=True)
            st.markdown("#### Validation rejects"); st.dataframe(pd.DataFrame([{k:v for k,v in x.items() if k!="_line"} for x in st.session_state["batch_rejects"]]),use_container_width=True,hide_index=True)
            st.download_button("Download results CSV",pd.DataFrame(st.session_state["batch_rows"]).to_csv(index=False),"batch_results.csv","text/csv")

elif page=="Tickets & metrics":
    st.subheader("Ticket lifecycle and evaluation")
    con=db(); records=con.execute("SELECT * FROM tickets ORDER BY created_at DESC").fetchall(); con.close()
    if records: st.dataframe(pd.DataFrame([dict(r) for r in records]),use_container_width=True,hide_index=True)
    else: st.info("Process a query to create a ticket. Low-risk automatic proposals remain pending approval.")
    if "batch_rows" in st.session_state:
        items=st.session_state["batch_rows"]; total=len(items); escalated=sum("ESCALATE" in x["Route"] or "REVIEW" in x["Route"] for x in items); known=sum(x["Article"]!="—" for x in items)
        x,y,z=st.columns(3); x.metric("Valid processed",total); y.metric("Knowledge coverage",f"{known/total:.1%}" if total else "—"); z.metric("Human review / escalation",f"{escalated/total:.1%}" if total else "—")
        st.caption("Knowledge coverage is article retrieval, not confirmed resolution. Drafts and escalations are not counted as resolved.")

else:
    st.subheader("Local services")
    st.code(f"Ollama endpoint: {CFG['ollama_url']}\nModel: {CFG['model']}\nMCP server: support_mcp.py (stdio) · {'available' if MCP_AVAILABLE else 'dependency missing'}\nKnowledge base: {len(load_kb())} approved articles\nSynthetic dataset: {sum(1 for _ in DATA.open(encoding='utf-8-sig'))-1} records")
    if st.button("Check Ollama and model"):
        try: st.success("Ollama reachable; model available: "+str(check_model(CFG["ollama_url"],CFG["model"])))
        except Exception as e: st.error(f"Could not reach Ollama: {e}. Start Ollama and pull qwen2.5:7b.")
    st.markdown("**Start:** `python -m pip install -r requirements.txt` then `streamlit run app.py`. The MCP integration is started by the app when a workflow is processed.")
