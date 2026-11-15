import json
from pathlib import Path

def load_kb(path=None):
    return json.loads(Path(path or Path(__file__).with_name("knowledge_base.json")).read_text(encoding="utf-8"))

def retrieve(query, kb, intent=None):
    text = query.lower()
    scores=[]
    for article in kb:
        if not article.get("approved"): continue
        words=[w for w in article["keywords"] if w.lower() in text]
        if words:
            score=round(100*len(words)/max(1,min(4,len(article["keywords"]))))
            if intent == article["intent"]: score=min(100,score+15)
            scores.append((score,article,words))
    if not scores: return None,0,[]
    score,article,words=max(scores,key=lambda x:x[0])
    return article, min(100,score), words

def route(classification, score, article):
    if classification["priority"] == "P1" or classification["intent"] == "Security Concern": return "URGENT_HUMAN_ESCALATION"
    if classification["complexity"] == "High": return "TECHNICAL_HUMAN_REVIEW"
    if not article: return "CREATE_TICKET_AND_ESCALATE"
    if score >= 70 and classification["complexity"] == "Low": return "PROPOSE_AUTO_RESOLUTION"
    if score >= 40: return "HUMAN_REVIEW"
    return "REQUEST_INFORMATION_OR_ESCALATE"
