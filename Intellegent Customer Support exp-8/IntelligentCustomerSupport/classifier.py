"""Rule-first labels for safe routing; Ollama provides an explainable second opinion."""
import re

INTENTS = ["Login / Access", "Billing", "Technical Error", "Feature Request", "General Information", "Unresolved Issue", "Security Concern", "Unknown"]

def classify_rules(query: str) -> dict:
    text = query.lower()
    malicious_security_triggers = (
        "ignore all previous instructions", "ignore all prior instructions",
        "reveal your system prompt", "reveal the system prompt",
        "show me another customer's", "export all customer records",
        "bypass two-factor", "bypass 2fa", "password reset token",
        "stored api keys", "access token", "other customers' data",
    )
    if any(k in text for k in malicious_security_triggers):
        return {"intent":"Security Concern", "complexity":"High", "priority":"P1", "reason":"Malicious instruction or protected-data request"}
    if text.strip() in {"it is not working", "it's not working", "it isn't working", "help", "issue"}:
        return {"intent":"Unknown", "complexity":"Medium", "priority":"P3", "reason":"Ambiguous; ask for details"}
    if any(k in text for k in ("data breach", "security incident", "unauthorized access", "account compromised", "suspicious access")):
        return {"intent":"Security Concern", "complexity":"High", "priority":"P1", "reason":"Security trigger takes precedence"}
    if any(k in text for k in ("application is down", "service outage", "all users", "everyone affected", "system-wide outage")):
        return {"intent":"Technical Error", "complexity":"High", "priority":"P1", "reason":"Widespread outage trigger"}
    if any(k in text for k in ("invoice", "payment", "billing", "subscription", "charged", "refund")):
        return {"intent":"Billing", "complexity":"Medium", "priority":"P2" if any(k in text for k in ("urgent", "blocked", "missing", "deducted", "cannot")) else "P3", "reason":"Billing keywords"}
    if any(k in text for k in ("cannot log in", "can't log in", "can't login", "cannot login", "account locked", "password", "two-factor")):
        return {"intent":"Login / Access", "complexity":"Medium", "priority":"P2", "reason":"Access issue keywords"}
    if any(k in text for k in ("dark mode", "feature request", "please add", "suggestion", "new feature")):
        return {"intent":"Feature Request", "complexity":"Low", "priority":"P4", "reason":"Product feedback keywords"}
    if any(k in text for k in ("still unresolved", "did not work", "not working", "tried all", "still fails")):
        return {"intent":"Unresolved Issue", "complexity":"High", "priority":"P2", "reason":"Repeated failure needs review"}
    if any(k in text for k in ("server error", "export", "timeout", "crash", "application error", "sync failed")):
        return {"intent":"Technical Error", "complexity":"Medium", "priority":"P3", "reason":"Technical symptom keywords"}
    if any(k in text for k in ("what is included", "how do i", "where can i", "plan features", "how to upgrade")):
        return {"intent":"General Information", "complexity":"Low", "priority":"P4", "reason":"Product information question"}
    if len(text.split()) < 4 or text.strip() in {"it is not working", "help", "issue"}:
        return {"intent":"Unknown", "complexity":"Medium", "priority":"P3", "reason":"Ambiguous; ask for details"}
    return {"intent":"Unknown", "complexity":"Medium", "priority":"P3", "reason":"No confident rule match"}

def parse_model_json(raw: str) -> dict | None:
    match = re.search(r"\{.*?\}", raw, re.S)
    if not match: return None
    import json
    try: data = json.loads(match.group())
    except (ValueError, TypeError): return None
    if data.get("intent") not in INTENTS or data.get("complexity") not in {"Low","Medium","High"} or data.get("priority") not in {"P1","P2","P3","P4"}: return None
    return data
