"""Thin end-to-end slice (SCRUM-54): one fine from login to approval through every service.

The agent run pauses when approval is pending and is resumed after each decision.

    uv run --with httpx python scripts/e2e_slice.py --fine FINE-1001
    uv run --with httpx python scripts/e2e_slice.py --fine FINE-1001 --gateway http://localhost:8080

Without --gateway the services are called directly on ports 8001 (auth), 8002 (domain), 8003 (agent).
"""
import argparse
import json
import sys

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--fine", default="FINE-1001", help="external fine id of a pending case")
parser.add_argument("--gateway", help="gateway base URL; omit to call the services directly")
parser.add_argument("--password", default="demo1234")
args = parser.parse_args()

if args.gateway:
    root = args.gateway.rstrip("/")
    AUTH, DOMAIN, AGENT = f"{root}/api/auth", f"{root}/api/domain/v1", f"{root}/api/agent"
else:
    AUTH, DOMAIN, AGENT = "http://localhost:8001", "http://localhost:8002/api/v1", "http://localhost:8003"

http = httpx.Client(timeout=180.0)


def call(method, url, token=None, **kwargs):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = http.request(method, url, headers=headers, **kwargs)
    if response.status_code >= 400:
        sys.exit(f"FAILED {method} {url} -> {response.status_code} {response.text[:500]}")
    return response.json()


def login(username):
    token = call("POST", f"{AUTH}/login", json={"username": username, "password": args.password})["access_token"]
    me = call("GET", f"{AUTH}/me", token)
    print(f"   logged in as {username} ({me['role']})")
    return token


def step(title):
    print(f"\n== {title}")


step("1. Login (auth-service)")
associate = login("demo_associate")

step("2. Work queue (domain-service)")
fines = call("GET", f"{DOMAIN}/fine-records", params={"page_size": 100})["items"]
fine = next((f for f in fines if f["external_fine_id"] == args.fine), None) or sys.exit(f"No fine {args.fine}")
queue = call("GET", f"{DOMAIN}/investigation-cases", params={"page_size": 100})["items"]
case = next((c for c in queue if c["fine_record_id"] == fine["id"]), None) or sys.exit("No open case for that fine")
print(f"   {len(queue)} cases in the queue; picked {args.fine}: {fine['metric']} fine, "
      f"${fine['original_amount']}, case status {case['status']}, origin {case['origin']}")

step("3. Investigation (agent-service)")
run = call("POST", f"{AGENT}/investigations", associate, json={"case_id": case["id"]})
print(f"   status: {run['status']}   model steps: {run['model_steps']}   run: {run['run_id']}")
print("   tools:  " + ", ".join(entry["tool"] for entry in run["tool_log"]))
if run["status"] != "awaiting_approval":
    handoff = call("GET", f"{DOMAIN}/investigation-cases/{case['id']}").get("handoff") or {}
    print(f"   handed off: {run.get('handoff_reason') or json.dumps(run.get('domain'))}")
    sys.exit(f"   recorded on the case: {'yes' if handoff.get('agent_run_id') == run['run_id'] else 'NO'}")
print(f"   paused for approval: {run['paused_for_approval']}")
found = run["findings"]
print(f"   cause: {found['cause']} ({found['confidence']} confidence)")
print(f"   summary: {found['summary']}")
for item in found["causes_checked"]:
    print(f"   - {item['cause']} {item['verdict']}: {item['reason']}")
for fact in found["verified_facts"]:
    print(f"   * {fact['fact']}  [{', '.join(r['record_type'] for r in fact['source_records'])}]")
if found["injected_instructions"]:
    print(f"   injected instructions reported: {found['injected_instructions']}")

step("4. Rules engine result (domain-service)")
outcome_id = run["domain"]["outcome_id"]
outcome = call("GET", f"{DOMAIN}/investigation-cases/{case['id']}/outcome")["items"][0]
line = outcome["line_outcomes"][0]
line = line.get("line_outcome", line)
print(f"   accountable: {line['accountable_party']}   proposal: {line['outcome']}   "
      f"${line['original_amount']} -> ${line['corrected_amount']} (reversal ${line['reversal_amount']})")

step("5. Approval (domain-service, JWT from auth-service)")
decision = {"line_outcome_id": line["id"], "stage": "associate", "decision": "approved", "comment": "e2e slice"}
call("POST", f"{DOMAIN}/outcomes/{outcome_id}/approvals", associate, json=decision)
run = call("POST", f"{AGENT}/investigations/{run['run_id']}/resume", associate)
print(f"   associate approved; agent run resumed -> {run['status']} ({run['approval_status']})")
approvals = call("GET", f"{DOMAIN}/outcomes/{outcome_id}/approvals")["items"]
if any(a["approval"]["approval_type"] == "manager" and a["approval"]["status"] == "pending" for a in approvals):
    manager = login("demo_manager")
    call("POST", f"{DOMAIN}/outcomes/{outcome_id}/approvals", manager, json={**decision, "stage": "manager"})
    run = call("POST", f"{AGENT}/investigations/{run['run_id']}/resume", manager)
    print(f"   manager approved (reversal above the threshold); agent run resumed -> {run['status']}")

final = call("GET", f"{DOMAIN}/investigation-cases/{case['id']}")["status"]
print(f"\nCase status: {final}   agent run: {run['status']}")
sys.exit(0 if final == "closed" and run["status"] == "approved" else 1)
