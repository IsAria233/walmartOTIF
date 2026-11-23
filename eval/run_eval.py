"""Run the agent on a generated dataset and score it against the expected answers.

The cases must already be loaded into domain-service (see data-gen/README.md).
A pending case is investigated through the gateway, exactly as the frontend does
it. A case that already has a result is scored from that result, so a run can be
repeated or continued without paying for the model again.

    EVAL_PASSWORD=... python eval/run_eval.py --dataset data-gen/dataset --out eval/reports/regression

Investigating calls the model: each pending case costs a few model calls.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scoring import observe, score, summarize  # noqa: E402

STARTABLE = {"pending", "revision_required"}
RUN_NAMESPACE = uuid.UUID("6f1d3c52-5a44-4c0e-9d57-0d1a4b6f7e21")


class Gateway:
    def __init__(self, root: str, username: str, password: str):
        self.root, self.username, self.password = root.rstrip("/"), username, password
        self.http = httpx.Client(timeout=300.0)
        self.token = self.login()

    def login(self) -> str:
        response = self.http.post(f"{self.root}/api/auth/login", json={"username": self.username, "password": self.password})
        response.raise_for_status()
        return response.json()["access_token"]

    def call(self, method: str, path: str, **kwargs) -> httpx.Response:
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self.token}", **kwargs.pop("headers", {})}
            response = self.http.request(method, f"{self.root}{path}", headers=headers, **kwargs)
            if response.status_code != 401 or attempt == 2:
                return response
            self.token = self.login()  # the token ran out during a long run
        return response

    def get(self, path: str) -> dict:
        response = self.call("GET", path)
        response.raise_for_status()
        return response.json()

    def pages(self, path: str):
        page = 1
        while True:
            data = self.get(f"{path}{'&' if '?' in path else '?'}page={page}&page_size=100")
            yield from data["items"]
            if page >= data["total_pages"]:
                return
            page += 1


def evaluate_case(gateway: Gateway, label: dict, fine_ids: dict[str, str], label_name: str, investigate: bool) -> dict:
    domain = "/api/domain/v1"
    fine_record_id = fine_ids.get(label["fine_id"])
    if fine_record_id is None:
        return {**score(label, observe({"status": "missing"}, None, None, {"fine_record": {"id": ""}})), "note": "fine not loaded"}
    cases = gateway.get(f"{domain}/investigation-cases?fine_record_id={fine_record_id}&sort_by=created_at&sort_order=desc")["items"]
    if not cases:
        return {**score(label, observe({"status": "missing"}, None, None, {"fine_record": {"id": ""}})), "note": "no case for this fine"}
    case_id = cases[0]["id"]
    run: dict = {}
    if investigate and cases[0]["status"] in STARTABLE:
        started = time.monotonic()
        # The same dataset and label always give the same key, so a repeated run continues instead of starting over.
        key = str(uuid.uuid5(RUN_NAMESPACE, f"{label_name}:{case_id}"))
        response = gateway.call("POST", "/api/agent/investigations", json={"case_id": case_id}, headers={"Idempotency-Key": key})
        run["seconds"] = round(time.monotonic() - started, 1)
        if response.status_code >= 400:
            run["error"] = f"{response.status_code} {response.text[:200]}"
        else:
            body = response.json()
            log = body.get("tool_log") or []
            run.update(run_id=body.get("run_id"), trace_id=body.get("trace_id"), model_steps=body.get("model_steps"),
                       tools_read=sum(entry["tool"] != "submit_findings" for entry in log),
                       rejected_submissions=sum(entry.get("accepted") is False for entry in log))

    case = gateway.get(f"{domain}/investigation-cases/{case_id}")
    context = gateway.get(f"{domain}/investigation-contexts/{fine_record_id}?case_id={case_id}")
    scoped = next((item for item in context.get("case_context", []) if item["case"]["id"] == case_id), {})
    latest = scoped.get("latest_finding")
    finding = gateway.get(f"{domain}/findings/{latest['id']}") if latest else None
    outcomes = gateway.get(f"{domain}/investigation-cases/{case_id}/outcome?page=1&page_size=1")["items"]
    line = outcomes[0]["line_outcomes"][0] if outcomes and outcomes[0]["line_outcomes"] else None
    return {**score(label, observe(case, finding, line, context)), "case_uuid": case_id,
            "case_status": case["status"], "run": run}


def markdown(summary: dict, rows: list[dict], meta: dict) -> str:
    def pct(value):
        return "n/a" if value is None else f"{value * 100:.1f}%"

    lines = [
        f"# Evaluation: {meta['label']}", "",
        f"Dataset `{meta['dataset']}` ({summary['cases']} cases), run {meta['finished_at']}.",
        f"{meta['investigated']} cases were investigated in this run; {summary['cases'] - meta['investigated']} were scored from an existing result.", "",
        "| Measure | Result |", "| --- | --- |",
        f"| Cause correct | {pct(summary['cause_accuracy'])} |",
        f"| Every check passed | {pct(summary['all_checks_passed'])} |",
        f"| Corrected fine correct (cases with an expected amount) | {pct(summary['amount_accuracy'])} |",
        f"| Handoffs that were right (precision) | {pct(summary['handoff_precision'])} |",
        f"| Expected handoffs that happened (recall) | {pct(summary['handoff_recall'])} |",
        f"| Injected instructions reported correctly | {pct(summary['injection_accuracy'])} |",
        f"| Key evidence cited, when the cause was right | {pct(summary['mean_evidence_recall_when_cause_right'])} |",
        f"| Cases with no result | {summary['no_result']} |", "",
        "## By expected cause", "", "| Expected | Cases | Correct |", "| --- | --- | --- |",
        *[f"| {cause} | {c['cases']} | {c['correct']} |" for cause, c in summary["by_expected_cause"].items()], "",
    ]
    failed = [row for row in rows if not row["passed"]]
    if failed:
        lines += ["## Cases that failed a check", "", "| Case | Scenario | Expected | Observed | Failed checks | Trace |", "| --- | --- | --- | --- | --- | --- |"]
        for row in failed:
            missed = ", ".join(name for name, ok in row["checks"].items() if not ok)
            lines.append(f"| {row['case_id']} | {row['scenario']} | {row['expected']} | {row['observed']} | {missed} | {(row.get('run') or {}).get('trace_id') or ''} |")
        lines.append("")
    steps = [row["run"]["model_steps"] for row in rows if (row.get("run") or {}).get("model_steps") is not None]
    seconds = [row["run"]["seconds"] for row in rows if (row.get("run") or {}).get("seconds") is not None]
    if steps:
        rejected = sum(row["run"].get("rejected_submissions", 0) for row in rows if row.get("run"))
        lines += ["## Runs in this evaluation", "",
                  f"Model steps per case: mean {sum(steps) / len(steps):.1f}, max {max(steps)}. "
                  f"Seconds per case: mean {sum(seconds) / len(seconds):.0f}, max {max(seconds):.0f}. "
                  f"Submissions rejected by the guardrail and retried: {rejected}.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, required=True, help="directory with cases.json and expected.json")
    parser.add_argument("--out", type=Path, required=True, help="directory for report.json and summary.md")
    parser.add_argument("--gateway", default="http://localhost:8080")
    parser.add_argument("--username", default="demo_associate")
    parser.add_argument("--label", help="name of this run; the default is the dataset directory's name")
    parser.add_argument("--limit", type=int, help="only the first N cases")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--score-only", action="store_true", help="do not start investigations; score what is stored")
    args = parser.parse_args()
    password = os.getenv("EVAL_PASSWORD")
    if not password:
        parser.error("set EVAL_PASSWORD to the demo account's password")

    labels = json.loads((args.dataset / "expected.json").read_text(encoding="utf-8"))["cases"][: args.limit]
    label_name = args.label or args.dataset.name
    gateway = Gateway(args.gateway, args.username, password)
    wanted = {label["fine_id"] for label in labels}
    fine_ids = {fine["external_fine_id"]: fine["id"] for fine in gateway.pages("/api/domain/v1/fine-records")
                if fine.get("external_fine_id") in wanted}

    def one(label: dict) -> dict:
        try:
            row = evaluate_case(gateway, label, fine_ids, label_name, not args.score_only)
        except httpx.HTTPError as error:
            row = {**score(label, observe({"status": "error"}, None, None, {"fine_record": {"id": ""}})), "note": str(error)[:200]}
        print(f"{'ok  ' if row['passed'] else 'MISS'} {row['case_id']} {row['scenario']}: expected {row['expected']}, observed {row['observed']}", flush=True)
        return row

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        rows = list(pool.map(one, labels))
    summary = summarize(rows)
    meta = {"label": label_name, "dataset": str(args.dataset), "gateway": args.gateway,
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "investigated": sum(bool((row.get("run") or {}).get("run_id")) for row in rows)}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps({"meta": meta, "summary": summary, "cases": rows}, indent=2) + "\n", encoding="utf-8")
    (args.out / "summary.md").write_text(markdown(summary, rows, meta) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Report written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
