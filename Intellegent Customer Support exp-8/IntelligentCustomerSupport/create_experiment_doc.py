"""Build the Experiment 08 report in Word format using the run evidence."""
import csv, json, textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.table import WD_ROW_HEIGHT_RULE
from docx.enum.section import WD_SECTION
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT=Path(__file__).parent
OUT=ROOT/"Experiment_08_Intelligent_Customer_Support_Report_Final.docx"
DATA=list(csv.DictReader((ROOT/"customer_queries.csv").open(encoding="utf-8-sig")))
RUNS=json.loads((ROOT/"experiment_query_results.json").read_text(encoding="utf-8"))
TESTS=json.loads((ROOT/"test_cases.json").read_text(encoding="utf-8"))
KB=json.loads((ROOT/"knowledge_base.json").read_text(encoding="utf-8"))

BLACK=RGBColor(0,0,0)
GRAY="EAEAEA"
FONT="Times New Roman"

def apply_font(run,size=10.5,bold=None,italic=None):
    run.font.name=FONT; run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"),FONT); run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"),FONT); run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"),FONT)
    run.font.size=Pt(size); run.font.color.rgb=BLACK
    if bold is not None: run.bold=bold
    if italic is not None: run.italic=italic
    return run

def set_cell_shading(cell,fill):
    tcPr=cell._tc.get_or_add_tcPr(); shd=OxmlElement("w:shd"); shd.set(qn("w:fill"),fill); tcPr.append(shd)

def set_cell_border(cell, color="000000", size="6"):
    tc=cell._tc; tcPr=tc.get_or_add_tcPr(); borders=tcPr.first_child_found_in("w:tcBorders")
    if borders is None: borders=OxmlElement("w:tcBorders"); tcPr.append(borders)
    for edge in ("top","left","bottom","right","insideH","insideV"):
        tag="w:"+edge; element=borders.find(qn(tag))
        if element is None: element=OxmlElement(tag); borders.append(element)
        element.set(qn("w:val"),"single"); element.set(qn("w:sz"),size); element.set(qn("w:color"),color)

def set_repeat_table_header(row):
    trPr=row._tr.get_or_add_trPr(); repeat=OxmlElement("w:tblHeader"); repeat.set(qn("w:val"),"true"); trPr.append(repeat)

def prevent_row_split(row):
    trPr=row._tr.get_or_add_trPr(); el=OxmlElement("w:cantSplit"); trPr.append(el)

def set_table_width(table,widths):
    if not widths: return
    total_twips=round(sum(widths)*1440)
    tbl_pr=table._tbl.tblPr; tbl_w=tbl_pr.find(qn("w:tblW"))
    if tbl_w is None: tbl_w=OxmlElement("w:tblW"); tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"),str(total_twips)); tbl_w.set(qn("w:type"),"dxa")
    for grid_col,width in zip(table._tbl.tblGrid.gridCol_lst,widths): grid_col.set(qn("w:w"),str(round(width*1440)))
    for row in table.rows:
        for cell,width in zip(row.cells,widths):
            cell.width=Inches(width)
            tc_pr=cell._tc.get_or_add_tcPr(); tc_w=tc_pr.find(qn("w:tcW"))
            if tc_w is None: tc_w=OxmlElement("w:tcW"); tc_pr.append(tc_w)
            tc_w.set(qn("w:w"),str(round(width*1440))); tc_w.set(qn("w:type"),"dxa")

def add_field(paragraph,code):
    run=paragraph.add_run(); begin=OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"),"begin")
    instr=OxmlElement("w:instrText"); instr.set(qn("xml:space"),"preserve"); instr.text=code
    separate=OxmlElement("w:fldChar"); separate.set(qn("w:fldCharType"),"separate")
    text=OxmlElement("w:t"); text.text="1"
    end=OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"),"end")
    run._r.extend([begin,instr,separate,text,end]); apply_font(run,8)

def add_para(doc,text="",style=None,size=10.5,bold=False,italic=False,align=None,before=0,after=5,keep=False):
    p=doc.add_paragraph(style=style) if style else doc.add_paragraph()
    p.paragraph_format.space_before=Pt(before); p.paragraph_format.space_after=Pt(after)
    if keep: p.paragraph_format.keep_with_next=True
    if align is not None: p.alignment=align
    if text: apply_font(p.add_run(str(text)),size,bold,italic)
    return p

def add_heading(doc,text,level=1):
    p=doc.add_paragraph(style=f"Heading {level}"); p.paragraph_format.keep_with_next=True
    p.paragraph_format.space_before=Pt(10 if level==1 else 7); p.paragraph_format.space_after=Pt(4)
    apply_font(p.add_run(text),16 if level==1 else 12.5,True)
    return p

def set_cell_text(cell,text,size=8.5,bold=False,align=None):
    cell.text=""; cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
    p=cell.paragraphs[0]; p.paragraph_format.space_before=Pt(1); p.paragraph_format.space_after=Pt(1); p.paragraph_format.line_spacing=1.0
    if align is not None: p.alignment=align
    apply_font(p.add_run(str(text)),size,bold)

def add_table(doc,headers,rows,widths=None,font=8.5):
    if widths and sum(widths)>6.65:
        factor=6.65/sum(widths); widths=[w*factor for w in widths]
    table=doc.add_table(rows=1,cols=len(headers)); table.alignment=WD_TABLE_ALIGNMENT.LEFT; table.autofit=False
    if widths:
        for col,w in zip(table.columns,widths): col.width=Inches(w)
    for j,h in enumerate(headers):
        set_cell_text(table.rows[0].cells[j],h,font,True,WD_ALIGN_PARAGRAPH.CENTER); set_cell_shading(table.rows[0].cells[j],GRAY); set_cell_border(table.rows[0].cells[j])
    set_repeat_table_header(table.rows[0]); prevent_row_split(table.rows[0])
    for row in rows:
        cells=table.add_row().cells; prevent_row_split(table.rows[-1])
        for j,val in enumerate(row):
            set_cell_text(cells[j],val,font,False); set_cell_border(cells[j])
            if widths: cells[j].width=Inches(widths[j])
    if widths: set_table_width(table,widths)
    add_para(doc,"",size=3,after=2)
    return table

def add_bullets(doc,items):
    for item in items:
        p=doc.add_paragraph(style="List Bullet"); p.paragraph_format.left_indent=Inches(.27); p.paragraph_format.first_line_indent=Inches(-.16); p.paragraph_format.space_after=Pt(2)
        apply_font(p.add_run(item),10.2)

def add_numbered(doc,items):
    for index,item in enumerate(items,1):
        p=doc.add_paragraph(); p.paragraph_format.left_indent=Inches(.28); p.paragraph_format.first_line_indent=Inches(-.28); p.paragraph_format.space_after=Pt(3)
        apply_font(p.add_run(f"{index}. {item}"),10.2)

def add_code(doc,code):
    table=doc.add_table(rows=1,cols=1); table.alignment=WD_TABLE_ALIGNMENT.LEFT; table.autofit=False; table.columns[0].width=Inches(6.65); set_table_width(table,[6.65])
    cell=table.cell(0,0); set_cell_shading(cell,"F5F5F5"); set_cell_border(cell,"000000","5"); cell.text=""
    p=cell.paragraphs[0]; p.paragraph_format.space_before=Pt(3); p.paragraph_format.space_after=Pt(3); p.paragraph_format.line_spacing=1.0
    apply_font(p.add_run(code.strip()),8.1)
    add_para(doc,"",size=3,after=1)

def draw_workflow(path):
    W,H=1800,1040; im=Image.new("RGB",(W,H),"white"); d=ImageDraw.Draw(im)
    font_path=r"C:\Windows\Fonts\times.ttf"; bold_path=r"C:\Windows\Fonts\timesbd.ttf"
    try: font=ImageFont.truetype(font_path,28); small=ImageFont.truetype(font_path,24); bold=ImageFont.truetype(bold_path,26)
    except OSError: font=ImageFont.load_default(); small=font; bold=font
    def box(x1,y1,x2,y2,title,lines=()):
        d.rounded_rectangle((x1,y1,x2,y2),radius=22,outline="black",width=4,fill="white")
        d.text(((x1+x2)//2,y1+20),title,font=bold,fill="black",anchor="mt")
        y=y1+64
        for line in lines:
            d.text(((x1+x2)//2,y),line,font=small,fill="black",anchor="mt"); y+=33
    def arrow(a,b):
        d.line((a,b),fill="black",width=5); import math
        ang=math.atan2(b[1]-a[1],b[0]-a[0]); length=18
        pts=[b,(b[0]-length*math.cos(ang-.45),b[1]-length*math.sin(ang-.45)),(b[0]-length*math.cos(ang+.45),b[1]-length*math.sin(ang+.45))]
        d.polygon(pts,fill="black")
    xs=[35,330,625,920,1215,1510]; bw=255; y=65; bh=185
    labels=[("Ingest",["CSV, JSON or chat","synthetic query"]),("Validate",["required fields","unique ID, nonempty"]),("Classify",["intent, complexity","priority: rules + Qwen"]),("Retrieve",["approved articles","keyword match score"]),("Assess risk",["heuristic score","P1/security first"]),("Route",["auto proposal","review or escalation"])]
    for x,(title,lines) in zip(xs,labels): box(x,y,x+bw,y+bh,title,lines)
    for i in range(5): arrow((xs[i]+bw+8,y+bh//2),(xs[i+1]-12,y+bh//2))
    box(125,390,520,575,"Proposed answer",["approved article only","await human approval"])
    box(650,390,1050,575,"Human support",["review, clarify or edit","ticket lifecycle"])
    box(1180,390,1680,575,"Urgent escalation",["P1, security, outage","priority queue"])
    arrow((1620,250),(1620,330)); d.text((1640,285),"by route",font=small,fill="black")
    arrow((1510,170),(780,350)); arrow((1510,205),(1350,350)); arrow((1510,225),(340,350))
    box(280,720,740,895,"Ticket and SLA",["priority deadlines","status and assignment"])
    box(870,720,1330,895,"Notification draft",["mock delivery","retry log"])
    box(1450,720,1730,895,"Audit and metrics",["event log","evaluation summary"])
    arrow((390,575),(465,705)); arrow((835,575),(590,705)); arrow((1430,575),(700,760))
    arrow((740,805),(855,805)); arrow((1335,805),(1435,805))
    d.text((W//2,980),"Every branch records its decision; drafts are not treated as completed resolutions.",font=small,fill="black",anchor="mm")
    im.save(path,dpi=(220,220))

diag=ROOT/"_workflow_diagram.png"; draw_workflow(diag)
doc=Document()
sec=doc.sections[0]; sec.top_margin=Inches(.62); sec.bottom_margin=Inches(.62); sec.left_margin=Inches(.68); sec.right_margin=Inches(.68)
sec.header_distance=Inches(.3); sec.footer_distance=Inches(.3)
styles=doc.styles
for name in ["Normal","Title","Subtitle","Heading 1","Heading 2","List Bullet","List Number"]:
    s=styles[name]; s.font.name=FONT; s._element.rPr.rFonts.set(qn("w:ascii"),FONT); s._element.rPr.rFonts.set(qn("w:hAnsi"),FONT); s.font.color.rgb=BLACK
styles["Normal"].font.size=Pt(10.5)
title_ppr=styles["Title"]._element.get_or_add_pPr(); title_border=title_ppr.find(qn("w:pBdr"))
if title_border is not None: title_ppr.remove(title_border)
# Minimal academic running header and page number footer.
h=sec.header.paragraphs[0]; h.alignment=WD_ALIGN_PARAGRAPH.RIGHT; apply_font(h.add_run("LABORATORY EXPERIMENT 08"),8,True)
f=sec.footer.paragraphs[0]; f.alignment=WD_ALIGN_PARAGRAPH.CENTER; apply_font(f.add_run("Intelligent Customer Support System  |  Page "),8); add_field(f,"PAGE")

# Cover and academic metadata.
add_para(doc,"EXPERIMENT NO. 08",size=14,bold=True,align=WD_ALIGN_PARAGRAPH.CENTER,before=35,after=16)
add_para(doc,"Intelligent Customer Support",style="Title",size=26,bold=True,align=WD_ALIGN_PARAGRAPH.CENTER,after=4)
add_para(doc,"System with Escalation",size=20,bold=True,align=WD_ALIGN_PARAGRAPH.CENTER,after=26)
add_para(doc,"Case study for a SaaS support workflow",size=13,align=WD_ALIGN_PARAGRAPH.CENTER,after=30)
add_table(doc,["Student details","Entry"],[
 ["Name","________________________________________"],["Roll number / class","________________________________________"],["Course / subject","________________________________________"],["D.O.P.","3rd Week of October"],["D.O.S.","4th Week of October"],["Submitted on","________________________________________"]],[2.1,4.8],10)
add_heading(doc,"Experiment Overview",2)
add_para(doc,"This experiment develops and examines a guided SaaS customer-support workflow. Queries are validated, classified, matched to approved knowledge, routed according to risk, and recorded as tickets when review or escalation is required. The report includes the 500-row synthetic dataset, representative local Qwen 2.5 7B runs, batch scenario results, safeguards, and evidence placeholders for screenshots.")
add_para(doc,"The tested examples show that model output can differ from the rule baseline. High-risk outage routing remained urgent, while ambiguous and unsupported questions were kept from automatic resolution. These observations support human review and careful evaluation of every generated draft.",after=0)
doc.add_page_break()

# Aim, objectives, tools.
add_heading(doc,"1 Aim",1)
add_para(doc,"To design, implement, and evaluate an intelligent customer-support system that classifies incoming SaaS queries by intent, complexity, and priority; retrieves approved knowledge; proposes grounded responses; creates and routes tickets; and supports human escalation, SLA tracking, audit logging, and batch evaluation.")
add_heading(doc,"2 Objectives",1)
add_numbered(doc,[
 "Ingest and validate customer queries from CSV or simulated chat input, including missing and duplicate fields.",
 "Classify intent, complexity, and priority with deterministic rules and a local Qwen 2.5 7B model.",
 "Retrieve only approved support articles and calculate a transparent keyword-match score.",
 "Route low-risk proposals, human review, and urgent security or outage cases to appropriate handling.",
 "Create SQLite ticket records with priority-based first-response deadlines.",
 "Display each workflow stage before showing the proposed response.",
 "Exercise normal, boundary, ambiguous, invalid, high-risk, and failure-oriented scenarios.",
 "Report executable test outcomes and identify important threat cases."
])
add_heading(doc,"3 Tools and Technology",1)
add_table(doc,["Tool or component","Use in the experiment"],[
 ["Python 3.10+","Modular workflow, validation, routing, ticket creation and report-data generation."],
 ["Streamlit","Guided step-by-step support page, batch-test page, ticket view and metrics."],
 ["Ollama with Qwen 2.5 7B Instruct","Local LLM classification and grounded response drafting at http://localhost:11434."],
 ["MCP Python SDK / FastMCP","Local support tool definitions for classification, approved-article search and workflow routing."],
 ["CSV and JSON","500 synthetic query records, approved knowledge articles, configuration and scenario definitions."],
 ["SQLite","Local ticket persistence when the interactive app creates tickets."],
 ["Pillow and python-docx","Black-and-white system diagram and this experiment report."]],[2.1,4.8],9)
add_para(doc,"The selected model installed on the local Ollama instance was qwen2.5:7b-instruct. This is an Ollama model tag for the Qwen 2.5 7B family; it runs locally rather than calling a hosted model API.",italic=True)
doc.add_page_break()

# Architecture and workflow.
add_heading(doc,"4 System Architecture and Workflow",1)
add_para(doc,"The application combines deterministic rules, the local Qwen model, an approved knowledge base, and a risk-first workflow router. FastMCP defines three local support tools. The Streamlit interface presents the stages in sequence so that the evidence behind the proposed route is visible before the response.")
add_table(doc,["Module","Responsibility"],[
 ["Query ingestion","Reads query fields and removes leading or trailing spaces."],
 ["Validation","Requires query ID, customer ID, query text and timestamp; rejects empty queries and duplicate IDs."],
 ["Classification","Assigns intent, complexity and P1-P4 priority using rules and schema-checked Qwen output."],
 ["Knowledge retrieval","Searches approved articles and returns the best keyword match and heuristic score."],
 ["Workflow router","Escalates P1 and security cases; otherwise routes for proposal, review, information or escalation."],
 ["Ticket and SLA","Creates ticket IDs, status, support team and illustrative first-response deadline."],
 ["Notification and audit","Uses notification drafts/simulations and records local ticket/workflow decisions."],
 ["Evaluation interface","Displays 14 scenario checks, dataset processing results, rejects and coverage indicators."]],[1.65,5.25],8.8)
add_heading(doc,"System Workflow Diagram",2)
p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_after=Pt(2)
p.add_run().add_picture(str(diag),width=Inches(6.65))
add_para(doc,"Figure 1. Local query processing and human-escalation workflow. The route selected by the system is a proposal; an answer draft is not itself proof that an issue was resolved.",size=8.5,italic=True,align=WD_ALIGN_PARAGRAPH.CENTER)
doc.add_page_break()

# Dataset description and actual content.
add_heading(doc,"5 Dataset Description and Content",1)
add_para(doc,"The file customer_queries.csv contains 500 synthetic CloudCRM support records. It uses customer IDs only and contains no real names, email addresses, or account credentials. A ground_truth_intent column is included for classroom comparison. The records span login/access, billing, technical errors, product information, feature requests, unresolved issues and security concerns.")
schema=[
 ["query_id","Synthetic query identifier; intentionally includes one duplicate."],
 ["customer_id","Synthetic customer key from C001 to C120."],
 ["query_text","Synthetic natural-language customer question; includes one empty record."],
 ["product","Product label; all starter records use CloudCRM."],
 ["created_at","Synthetic timestamp at three-minute intervals beginning 20 Oct 2026."],
 ["ground_truth_intent","Scenario label for classroom comparison; boundary labels are explicitly named."]]
add_table(doc,["Column","Description"],schema,[1.75,5.15],9)
counts={}
for row in DATA: counts[row["ground_truth_intent"]]=counts.get(row["ground_truth_intent"],0)+1
add_para(doc,f"Dataset size: {len(DATA)} rows. Validation accepts 498 rows and rejects 2 rows in the full file: one duplicate query ID and one empty query. The labeled rows include {counts.get('Billing',0)} standard Billing examples, {counts.get('Technical Error',0)} Technical Error examples, {counts.get('General Information',0)} General Information examples, {counts.get('Login / Access',0)} Login / Access examples, {counts.get('Feature Request',0)} Feature Request examples, {counts.get('Unresolved Issue',0)} Unresolved Issue examples, and {counts.get('Security Concern',0)} Security Concern examples. Four additional rows are named boundary or priority fixtures.")
add_heading(doc,"Dataset Content Sample",2)
sample=[]
for row in DATA[:10]: sample.append([row["query_id"],row["customer_id"],row["query_text"],row["created_at"],row["ground_truth_intent"]])
add_table(doc,["Query ID","Customer","Query text","Created","Ground truth"],sample,[.56,.63,3.15,1.0,1.56],7.4)
add_heading(doc,"Required Boundary Records",2)
special=DATA[-5:]
add_table(doc,["Record","Dataset content","Purpose"],[
 ["Duplicate ID",f"{DATA[494]['query_id']} appears on two different rows.","Checks unique-ID validation."],
 ["High-priority billing",special[1]["query_text"],"Checks billing classification with explicit urgency."],
 ["Empty query", "Blank query_text in the row labeled Invalid empty query.","Checks nonempty-text validation."],
 ["Ambiguous query",special[3]["query_text"],"Checks request-for-details behavior."],
 ["No KB match",special[4]["query_text"],"Checks that unsupported claims are not invented."]],[1.25,3.35,2.3],8.2)
add_para(doc,"The file is deterministic and can be regenerated with generate_dataset.py. The CSV is the complete dataset; the table above is a readable excerpt rather than a printout of all 500 rows.",italic=True)
doc.add_page_break()

# Methods.
add_heading(doc,"6 Methods",1)
add_para(doc,"The workflow follows the order below. Each step records evidence used by the next step; the final draft is displayed only after the input, labels, article match, route, and ticket decision are shown.")
add_numbered(doc,[
 "Ingest: read the CSV record or the text entered in the simulated support interface.",
 "Validate: trim fields, verify required values, reject empty text, and flag duplicate IDs.",
 "Classify: apply safety-sensitive rule precedence, then ask local Qwen for structured intent, complexity and priority when enabled.",
 "Validate model output: accept only listed intent, complexity and priority labels. On malformed JSON or model failure, use the rule-based classification.",
 "Retrieve: search only knowledge articles marked approved and calculate the keyword-match heuristic.",
 "Route: prioritize P1 and security conditions, then high complexity, missing knowledge, match score and review thresholds.",
 "Draft and track: create a response using the selected article, create a ticket for review/escalation, set the sample SLA deadline, and show notification/audit status.",
 "Evaluate: run test scenarios and inspect accepted/rejected rows, observed routes, article coverage and manually labeled outcomes."
])
add_heading(doc,"Classification and Retrieval",2)
add_para(doc,"The rule classifier labels each query across three dimensions. Security incidents and service-wide outages are P1 and high complexity. Billing, access, technical error, feature request, general information, unresolved issues and unknown/ambiguous questions use explicit keyword and context rules. The Qwen JSON output is constrained to the same label set and validated before use.")
add_para(doc,"For each approved article, the resolver counts query keywords that appear in the customer text and divides by up to four article keywords, then applies a small intent-match adjustment. The result is an experimental heuristic match score, not a calibrated probability of correctness. In the observed runs, for example, the login query matched two terms and scored 65% after the intent adjustment.")
add_heading(doc,"Routing Thresholds",2)
add_table(doc,["Condition","Proposed route"],[
 ["P1, security concern or widespread outage","Urgent human escalation, independent of article score."],
 ["High complexity","Technical human review."],
 ["No approved article","Create ticket and escalate; do not invent an answer."],
 ["Match score at least 70 and low complexity","Propose an automatic response for approval."],
 ["Match score at least 40","Human review."],
 ["Lower match score","Request information or escalate."]],[3.05,3.85],8.7)
add_heading(doc,"Ticket and SLA Handling",2)
add_para(doc,"Tickets use generated TCK identifiers, a support queue, status, creation time and first-response deadline. Illustrative configuration targets are P1 15 minutes, P2 60 minutes, P3 240 minutes and P4 1,440 minutes. They are classroom values rather than contractual targets. An automated proposal is stored as pending approval; it is not labeled resolved. Notification delivery is a mock/draft path in this project.")
doc.add_page_break()

# Important code.
add_heading(doc,"7 Important Code and Safeguards",1)
add_heading(doc,"Input Validation",2)
add_code(doc,"""required = ("query_id", "customer_id", "query_text", "created_at")
for row in rows:
    row = {key: str(value or "").strip() for key, value in row.items()}
    errors = [f for f in required if not row.get(f)]
    if row.get("query_id") in seen_ids:
        errors.append("Duplicate query_id")
    if errors:
        rejected.append({"record": row, "errors": errors})
    else:
        seen_ids.add(row["query_id"])
        valid.append(row)""")
add_para(doc,"The implementation treats a repeated query ID as invalid and records the reason. It does not send rejected records through normal classification.")
add_heading(doc,"MCP Tool Definitions",2)
add_code(doc,"""@mcp.tool()
def classify_support_query(query: str) -> dict:
    return classify_rules(query)

@mcp.tool()
def search_approved_knowledge(query: str, intent: str = "") -> dict:
    article, score, matched = retrieve(query, load_kb(), intent or None)
    return {"article": article, "score": score, "matched_keywords": matched}

@mcp.tool()
def decide_support_route(intent, complexity, priority, score, article_found):
    labels = {"intent": intent, "complexity": complexity, "priority": priority}
    article = {"approved": True} if article_found else None
    return {"route": route(labels, score, article)}""")
add_para(doc,"The first two functions are concise examples of the local tool handlers registered in support_mcp.py. The production source passes a structured classification to the router and returns the selected route.")
add_heading(doc,"Risk First Routing",2)
add_code(doc,"""if classification["priority"] == "P1" \\
        or classification["intent"] == "Security Concern":
    return "URGENT_HUMAN_ESCALATION"
if classification["complexity"] == "High":
    return "TECHNICAL_HUMAN_REVIEW"
if not article_found:
    return "CREATE_TICKET_AND_ESCALATE"
if score >= 70 and classification["complexity"] == "Low":
    return "PROPOSE_AUTO_RESOLUTION"
if score >= 40:
    return "HUMAN_REVIEW"
return "REQUEST_INFORMATION_OR_ESCALATE"
""")
add_heading(doc,"Safeguards Included",2)
add_bullets(doc,[
 "The Qwen model runs through the local Ollama service; the query examples are synthetic.",
 "Only approved knowledge articles are eligible for retrieval.",
 "Security and P1 outage rules take precedence over the model classification.",
 "Malformed model JSON or invalid labels trigger a rule-based fallback; EXP02 exercised this fallback.",
 "No knowledge match produces no generated answer; EXP06 confirms this behavior.",
 "Generated responses remain drafts and are not treated as completed resolutions or sent notifications.",
 "The keyword score is explicitly a heuristic rather than a probability.",
 "The batch suite includes executable prompt-injection, data-exfiltration and credential-abuse checks."
])
add_para(doc,"Observed limitation: the P1 override is strong, but the app can accept a Qwen P2-to-P3 or P4-to-P3 downgrade for noncritical cases. EXP01 and EXP04 show this. A production-oriented improvement would preserve deterministic priority floors and treat exact short queries as ambiguous before accepting model labels.",size=9.5)

# Batch tables, based on the app test-case definitions.
byid={x["test_id"]:x for x in TESTS}
def table_rows(ids,observed):
    result=[]
    for tid in ids:
        t=byid[tid]; value,status=observed[tid]
        result.append([tid,t["scenario"],t.get("query","") or "<empty query_text>",t["expected"],value,status])
    return result

add_heading(doc,"8 Batch Test Tables",1)
add_para(doc,"The 14-row suite is grouped by test type. TC01–TC10 cover normal, boundary and risk-first cases. MAL01–MAL04 are malicious-input queries executed by the application's batch scenario runner against its deterministic security rules and routing.")
actual={
 "TC01":("Login / Access","PASS"),"TC02":("Billing","PASS"),"TC03":("P1 · urgent human escalation","PASS"),
 "TC04":("Feature Request","PASS"),"TC05":("Rejected: Missing or empty query_text","PASS"),"TC06":("Duplicate rejected: Duplicate query_id","PASS"),
 "TC07":("CREATE_TICKET_AND_ESCALATE · no article","PASS"),"TC08":("PROPOSE_AUTO_RESOLUTION · 90% match","PASS"),
 "TC09":("REQUEST_INFORMATION_OR_ESCALATE (ambiguous)","PASS"),"TC10":("URGENT_HUMAN_ESCALATION","PASS")}
malicious={
 "MAL01":("Security Concern · High · P1 · URGENT_HUMAN_ESCALATION","PASS"),
 "MAL02":("Security Concern · High · P1 · URGENT_HUMAN_ESCALATION","PASS"),
 "MAL03":("Security Concern · High · P1 · URGENT_HUMAN_ESCALATION","PASS"),
 "MAL04":("Security Concern · High · P1 · URGENT_HUMAN_ESCALATION","PASS")}
add_heading(doc,"8.1 Normal Support Queries",2)
add_table(doc,["ID","Test type","Query","Expected","Observed result","Status"],table_rows(["TC01","TC02","TC04","TC08"],actual),[.42,1.03,2.25,1.05,1.55,.6],7.2)
add_heading(doc,"8.2 Validation Boundary and Knowledge Gaps",2)
add_table(doc,["ID","Test type","Query or input","Expected","Observed result","Status"],table_rows(["TC05","TC06","TC07","TC09"],actual),[.42,1.03,2.25,1.05,1.55,.6],7.2)
add_heading(doc,"8.3 High Priority and Security",2)
add_table(doc,["ID","Test type","Query","Expected","Observed result","Status"],table_rows(["TC03","TC10"],actual),[.42,1.03,2.25,1.05,1.55,.6],7.2)
doc.add_page_break()
add_heading(doc,"8.4 Malicious and Prompt Injection Queries",2)
mal_rows=[]
for tid in ("MAL01","MAL02","MAL03","MAL04"):
    t=byid[tid]; observed,status=malicious[tid]
    mal_rows.append([tid,t["scenario"],t["query"],observed,status])
add_table(doc,["ID","Test type","Malicious query","Observed result","Status"],mal_rows,[.48,1.15,2.45,2.27,.65],7.0)
add_para(doc,"All four malicious queries were run using the application's batch rules. Each matched an explicit security trigger, received P1 and routed to urgent human escalation. In the guided workflow, Security Concern cases also skip Qwen response drafting, so an injected instruction is not used to generate a customer-facing answer. These tests cover the listed phrases; they do not prove detection of every malicious wording.",italic=True)
add_heading(doc,"Batch Test Summary",2)
add_table(doc,["Measure","Observed value","Interpretation"],[
 ["Standard application checks","10 passed, 0 failed","TC01–TC10 ran through the app's deterministic scenario runner."],
 ["Malicious input checks","4 passed, 0 failed","MAL01–MAL04 matched the deterministic security rules and routed to urgent human escalation."],
 ["Combined scenario suite","14 passed, 0 failed","All 14 checks are executed by the application scenario runner; the suite does not test external notification or ticket lifecycle operations."],
 ["Dataset validation","498 accepted, 2 rejected","The full dataset contains one empty query and one duplicate query ID."],
 ["KB article coverage","7 approved articles","Coverage is not a resolution rate."],
 ["Model structured output","5 valid / 6 examples","One malformed/invalid Qwen classification fell back to the deterministic rules." ]],[1.6,1.5,3.8],8.2)
doc.add_page_break()

# Six observed queries, each with its own screenshot slot.
insights={
 "EXP01":"The local Qwen model retained the Login / Access intent and proposed steps grounded in KB001. It changed the rule baseline from P2 Medium to P3 Low, so the retrieved article still went to human review at a 65% heuristic match. The priority downgrade is visible and should be reviewed before relying on model priority labels.",
 "EXP02":"Qwen did not return acceptable structured JSON for this run, so the application used the rule classification. Billing intent and P2 priority were retained, KB002 supplied the response draft, and the 65% match routed the case to human review. The fallback kept the query in a controlled path.",
 "EXP03":"Qwen's label differed from the rule label, but the explicit outage rule preserved Technical Error, High complexity and P1. The route was urgent human escalation. No article matched, so the system correctly withheld a substantive answer instead of inventing outage status or recovery timing.",
 "EXP04":"Qwen recognized the product suggestion and selected KB005. It raised the rule priority from P4 to P3 and routed the 65% match for human review. The response correctly described the item as a suggestion and did not promise a release date.",
 "EXP05":"This short query is ambiguous, but Qwen labeled it Technical Error, Low and P3 while the rule baseline called it an unresolved issue. The route requested information or escalation at a 25% match. The generated draft refers to earlier troubleshooting even though the query did not say any steps were tried; this shows why ambiguous drafts need human review and better ambiguity detection.",
 "EXP06":"Qwen interpreted the unsupported question as a feature request, but no approved article matched. The system created an escalation route and returned no invented answer. The route remained cautious even though the intent label was not the only reasonable interpretation."
}
for i,run in enumerate(RUNS,1):
    if i>1: doc.add_page_break()
    add_para(doc,f"9.{i} Observed Query Run {run['query_id']}",size=16,bold=True,before=5,after=4,keep=True)
    add_para(doc,"Screenshot heading: "+run["query_id"]+"  |  Guided support result",size=10,bold=True)
    add_para(doc,"Query: “"+run["query_text"]+"”",size=11,bold=True)
    c=run["final_classification"]
    add_table(doc,["Stage","Observed result"],[
     ["MCP rule classification",f"{run['mcp_classification']['intent']} · {run['mcp_classification']['complexity']} · {run['mcp_classification']['priority']}"],
     ["Qwen classification",f"{run['qwen_classification']['intent']} · {run['qwen_classification']['complexity']} · {run['qwen_classification']['priority']}"+(" · deterministic fallback" if run.get("qwen_error") else "")],
     ["Final classification",f"{c['intent']} · {c['complexity']} · {c['priority']}"],
     ["Approved article / match",f"{run['article_id'] or 'None'} · {run['match_score']}% heuristic score"],
     ["Workflow route",run["route"]],
     ["Observed model latency",f"{run['qwen_classification_seconds']:.2f} s for structured classification" if run["qwen_classification_seconds"] else "Rule fallback after invalid model JSON"]
    ],[1.8,5.1],8.3)
    add_para(doc,"Observed response: "+run["response_draft"],size=9.2)
    # Explicitly reserved for the student's own screenshot.
    placeholder=doc.add_table(rows=1,cols=1); placeholder.alignment=WD_TABLE_ALIGNMENT.LEFT; placeholder.autofit=False; placeholder.columns[0].width=Inches(6.65); set_table_width(placeholder,[6.65])
    placeholder.rows[0].height=Inches(1.75); placeholder.rows[0].height_rule=WD_ROW_HEIGHT_RULE.AT_LEAST
    cell=placeholder.cell(0,0); cell.width=Inches(6.65); cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER; set_cell_border(cell,"000000","10")
    set_cell_text(cell,"PASTE SCREENSHOT HERE\nCapture the guided support page showing the query, workflow steps, route and proposed response.",9,False,WD_ALIGN_PARAGRAPH.CENTER)
    add_para(doc,"Inference to place below the screenshot: "+insights[run["query_id"]],size=9.2,before=5,after=2)

# Results, inference and conclusion.
doc.add_page_break()
add_heading(doc,"10 Results",1)
add_table(doc,["Observed result","Evidence"],[
 ["Dataset is large enough for classroom batch evaluation","500 synthetic CSV records; 498 valid and 2 intentionally invalid."],
 ["Knowledge content is bounded","Seven approved articles are searchable; no article is returned for the unsupported EXP06 query."],
 ["Risk-first escalation operated in the outage example","The Qwen intent label differed, while the explicit P1 outage rule retained urgent escalation."],
 ["Model output needed a fallback","Five of six selected queries returned accepted JSON; EXP02 used the rule-based fallback."],
 ["Selected-sample latency","Mean Qwen structured-classification time was 6.68 s for the five valid-JSON responses; this is a small sample, not a benchmark."],
 ["Executable batch checks","14 passed and 0 failed, including four malicious-input cases; notification/lifecycle cases are not included because those app features are not implemented."],
 ["Automatic resolution was not claimed","Drafts and escalations remain proposals; the observed sample does not measure completed resolution or SLA compliance."]],[2.0,4.9],8.4)
add_heading(doc,"11 Inference",1)
add_para(doc,"The workflow demonstrates value from combining rule-based risk checks, approved knowledge retrieval, a local language model, and explicit human routes. The outage case shows that a deterministic P1 safeguard can prevent a model's inconsistent intent label from bypassing urgent handling. The unsupported query shows that article absence can prevent fabricated product claims.")
add_para(doc,"The sample also exposes limits. Qwen changed ordinary priority labels in the login and feature-request examples, and it produced invalid structured JSON once. The ambiguous query received an over-specific draft that implied earlier steps had been attempted. Therefore, the observed output supports a human-approval policy, stronger priority constraints, an explicit ambiguity check, and query-to-article entailment review. Six chosen examples cannot establish overall classification accuracy, resolution rate, or fairness.")
add_heading(doc,"12 Conclusion",1)
add_para(doc,"The Intelligent Customer Support System implements a modular SaaS support flow with CSV validation, intent/complexity/priority classification, MCP tool handlers, local Qwen 2.5 7B inference, approved knowledge retrieval, risk-based routing, ticket/SLA configuration, notification drafts, audit-oriented records, and batch evaluation. Its 500-row synthetic dataset includes the required invalid and boundary cases.")
add_para(doc,"In the observed query runs, urgent outage escalation and no-knowledge abstention behaved as intended. Model priority shifts, malformed output, and an over-specific ambiguous-query draft show why model responses must remain reviewable. Four malicious-input cases also triggered the security route in the batch runner. The experiment meets its objectives as a classroom prototype and leaves notification delivery, full lifecycle transitions, SLA measurement, and larger-scale accuracy analysis as future implementation and evaluation work.")
add_heading(doc,"Project Files Used",2)
add_para(doc,"app.py · classifier.py · resolver.py · ollama_client.py · support_mcp.py · mcp_client.py · customer_queries.csv · knowledge_base.json · config.json · test_cases.json · experiment_query_results.json")

# Normalize any remaining style-only runs, enforce black font and table style.
for p in doc.paragraphs:
    for r in p.runs: r.font.color.rgb=BLACK
for table in doc.tables:
    for row in table.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                for r in p.runs: r.font.color.rgb=BLACK
doc.core_properties.title="Experiment 08 Intelligent Customer Support System with Escalation"
doc.core_properties.subject="Laboratory experiment report with synthetic dataset, local Qwen results, MCP tools and batch tests"
doc.core_properties.author=""
doc.save(OUT)
print(OUT)


