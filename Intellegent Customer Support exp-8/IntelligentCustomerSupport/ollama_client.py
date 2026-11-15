import requests
from classifier import parse_model_json

def check_model(base_url, model):
    response=requests.get(base_url.rstrip("/")+"/api/tags",timeout=3)
    response.raise_for_status()
    names=[m.get("name","") for m in response.json().get("models",[])]
    return next((n for n in names if n==model or n.startswith(model.split(":")[0]+":")),None)

def classify_with_ollama(query, base_url, model):
    prompt=("Classify this SaaS support query. Return ONLY JSON with intent from [Login / Access, Billing, Technical Error, Feature Request, General Information, Unresolved Issue, Security Concern, Unknown], complexity [Low, Medium, High], priority [P1, P2, P3, P4], and short reason. P1 for security/widespread outage; do not infer severity from emotional wording. Query: "+query)
    response=requests.post(base_url.rstrip("/")+"/api/generate",json={"model":model,"prompt":prompt,"stream":False,"format":"json","options":{"temperature":0}},timeout=120)
    response.raise_for_status()
    result=response.json()
    parsed=parse_model_json(result.get("response",""))
    if not parsed: raise ValueError("Model returned invalid classification JSON")
    return parsed, result.get("total_duration",0)/1e9

def grounded_draft(query, article, base_url, model):
    prompt=("Write a concise customer support draft using only the approved article. If it does not answer the query, say so and ask a clarifying question. Do not invent policy or claim actions were taken.\nCustomer query: "+query+"\nApproved article: "+article["response"])
    response=requests.post(base_url.rstrip("/")+"/api/generate",json={"model":model,"prompt":prompt,"stream":False,"options":{"temperature":0.2}},timeout=120)
    response.raise_for_status()
    return response.json().get("response","").strip()
