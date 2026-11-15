"""Regenerate the deterministic, fully synthetic classroom query dataset."""
import csv
from datetime import datetime,timedelta
from pathlib import Path

templates=[
 ("I cannot log in to my account after resetting my password", "Login / Access"),
 ("My account is locked and I need help restoring access", "Login / Access"),
 ("The two-factor authentication code is not accepted", "Login / Access"),
 ("Where can I find the invoice for my subscription?", "Billing"),
 ("My payment was deducted but the invoice is missing", "Billing"),
 ("Please check the billing status for my workspace", "Billing"),
 ("How can I upgrade my plan and review the features?", "General Information"),
 ("What is included in the basic plan?", "General Information"),
 ("The report export returns an internal server error", "Technical Error"),
 ("File upload keeps timing out in the dashboard", "Technical Error"),
 ("Please add dark mode to the application", "Feature Request"),
 ("I suggest adding a weekly summary feature", "Feature Request"),
 ("I tried all suggested steps and it is still not working", "Unresolved Issue"),
 ("The issue did not work after retrying the troubleshooting steps", "Unresolved Issue"),
 ("Security incident: suspicious unauthorized access to our account", "Security Concern"),
 ("The application is down for all users in our company", "Technical Error"),
 ("How do I update my workspace notification preferences?", "General Information"),
 ("The dashboard sync failed after the latest refresh", "Technical Error"),
 ("My subscription renewal charge looks incorrect, please investigate urgently", "Billing"),
 ("I need help understanding the settings in my account", "General Information")]
rows=[]; start=datetime(2026,10,20,9,0)
for i in range(1,501):
    if i==498: text=""; label="Invalid empty query"
    elif i==499: text="It is not working"; label="Ambiguous"
    elif i==500: text="Can your service connect to a fictional quantum flux capacitor?"; label="No KB match"
    elif i==497: text="My payment was deducted but the invoice is missing and this is urgent"; label="Billing high priority"
    else: text,label=templates[(i-1)%len(templates)]
    qid="Q%04d"%(i if i!=496 else 495) # Q0496 duplicates Q0495 intentionally.
    rows.append({"query_id":qid,"customer_id":"C%03d"%((i-1)%120+1),"query_text":text,"product":"CloudCRM","created_at":(start+timedelta(minutes=3*(i-1))).strftime("%Y-%m-%d %H:%M"),"ground_truth_intent":label})
path=Path(__file__).with_name("customer_queries.csv")
with path.open("w",newline="",encoding="utf-8") as f:
    writer=csv.DictWriter(f,fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
print(f"Wrote {len(rows)} synthetic rows to {path}")
