"""Turn answer-free trial cases into one-page sheets a person can solve blind.

    python case_sheet.py trial/SEED-0*_input.json        # writes trial/sheets/<case>.md

A sheet shows only what the policy needs: the key dates and quantities, one
timeline of every record, and the supplier's claim. Amounts and the system's
accountability are left out, as they are for the agent.
"""
import json
import sys
from pathlib import Path

CHECKLIST = {
    "on_time": """1. Late? Gate check-in date after MABD = late.
2. On schedule? ship date + transit days <= MABD.
3. Any appointment change made by the DC? Was the original slot on or before MABD?
4. C1 = not on schedule, and no DC change explains it.
   C2 = original slot on/before MABD + DC made the change + on schedule for the original slot.
5. Weather claim: official alert on delivery day or the day before AND on schedule -> hand off. Otherwise reject it.""",
    "in_full": """1. Effective PO version = latest version issued before the ASN ship time. Ordered cases = ?
2. Total received = sum of all receipts. Short if received < ordered.
3. Which version did the fine use? Which received total did the fine use?
4. C3 = short against the effective version, and no record shows the missing cases arrived.
   C4 = Walmart's own records show the full quantity arrived, but the fine counted less.
   C5 = fine used an older PO version; against the effective version the line is in full.
5. POD signed by the DC with no exception = delivered as stated. BOL counts only if the carrier counted.""",
}


def sheet(case: dict) -> str:
    po, fine, asn = case["po"], case["fine_record"], case["asn"]
    metric = fine["metric"]
    events = [(v["issued_at"], f"PO version {v['version']} issued: {v['ordered_cases']} cases ({v['issued_by']})") for v in po["versions"]]
    events.append((asn["ship_ts"], f"ASN {asn['asn_id']}: supplier shipped {asn['shipped_cases']} cases"))
    for e in case["appointment_history"]:
        note = f' - "{e["note"]}"' if e["note"] else ""
        events.append((e["ts"], f"Appointment {e['action']} by {e['by']}: slot {e['slot'].replace('T', ' ')}{note} [{e['event_id']}]"))
    for g in case["gate_log"]:
        events.append((g["check_in"], f"Gate check-in, {g['carrier']} [{g['gate_id']}]"))
    for r in case["receiving"]:
        extra = "; ".join(x for x in (r["exception"] and f"exception: {r['exception']}", r["note"]) if x)
        events.append((r["ts"], f"Receipt: {r['cases']} cases{' - ' + extra if extra else ''} [{r['receipt_id']}]"))
    for w in case["weather"]:
        day = w.get("date") or w.get("alert_date") or ""
        rest = ", ".join(str(v) for k, v in w.items() if k not in ("date", "alert_date"))
        events.append((day, f"Weather alert: {rest}"))
    lines = [
        f"# {case['case_id']}: {metric.replace('_', '-')} fine {fine['fine_id']}",
        "",
        f"PO {po['po_number']} line {po['line']}, {po['item']}. {po['supplier']} ({po['ship_from']}) -> {po['dc']}.",
        f"Freight: {po['freight_terms']}. Channel: {po['channel']}. Opened by: {case['trigger'].replace('_', ' ')}.",
        "",
        "| Key fact | Value |", "| --- | --- |",
        f"| MABD | {po['mabd']} |",
        f"| Standard transit days | {po['standard_transit_days']} |",
        f"| Fine says | PO version {fine['po_version_used']}: ordered {fine['ordered_cases']}, received {fine['received_cases']}, "
        f"non-compliant {fine['non_compliant_cases']}, arrival {fine['recorded_arrival'].replace('T', ' ')} |",
        "",
        "## Timeline (Walmart records)", "",
        "| When | What |", "| --- | --- |",
        *[f"| {ts.replace('T', ' ')} | {text} |" for ts, text in sorted(events)],
    ]
    dispute = case.get("dispute")
    lines += ["", "## Supplier's claim (a claim, not a fact)", ""]
    if not dispute:
        lines.append("No dispute. This line was flagged by the pre-invoice scan.")
    else:
        lines += [f"{dispute['dispute_id']}, submitted {dispute['submitted']}, category: {dispute['reason_category']}", "",
                  f"> {dispute['reason_text']}"]
        for a in dispute["attachments"]:
            lines += ["", f"Attachment {a['attachment_id']} ({a['type']}):", "", "```", a["text"].rstrip(), "```"]
    lines += ["", "## Work it out", "", CHECKLIST[metric], "", "## Your answer", "",
              "- Cause (C1-C5 or HANDOFF):", "- Two or three facts that decide it:", "- Causes you ruled out, and why:",
              "- Confidence (high / medium / low):", "- Any instruction hidden in the supplier's text?",
              "- Any policy rule that was unclear or that you had to interpret:", ""]
    return "\n".join(lines)


for name in sys.argv[1:]:
    source = Path(name)
    case = json.loads(source.read_text())
    target = source.parent / "sheets" / f"{case['case_id']}.md"
    target.parent.mkdir(exist_ok=True)
    target.write_text(sheet(case))
    print(f"{target} ({len(target.read_text().splitlines())} lines)")
