"""Checks that each seed case is internally consistent with docs/otif_policy.md.

Usage: python check_seed_cases.py seed_cases.json

It recomputes the system fine from the fine record, then derives the correct
cause and corrected fine from the underlying records, and compares both with
the case's stored values. Weather handoffs and POD tie-breaks (policy 4.3, 4.5)
are not derived here; the five seed cases do not need them.
"""
import json
import sys
from datetime import date, datetime, timedelta

RATE = 0.03


def d(ts):
    return datetime.fromisoformat(ts).date() if "T" in ts else date.fromisoformat(ts)


def derive(case):
    po, asn, fine = case["po"], case["asn"], case["fine_record"]
    mabd, cost = d(po["mabd"]), po["case_cost"]
    ship = d(asn["ship_ts"])
    if fine["metric"] == "on_time":
        cases_late = fine["non_compliant_cases"]
        on_schedule = ship + timedelta(days=po["standard_transit_days"]) <= mabd
        events = case["appointment_history"]
        for prev, cur in zip(events, events[1:]):
            moved_past = d(prev["slot"]) <= mabd < d(cur["slot"])
            reachable = ship + timedelta(days=po["standard_transit_days"]) <= d(prev["slot"])
            if cur["by"] == "DC" and moved_past and reachable:
                return "C2", "walmart", 0.0
        if not on_schedule:
            return "C1", "supplier", round(cases_late * cost * RATE, 2)
        return "HANDOFF", None, None
    # in_full
    ship_ts = datetime.fromisoformat(asn["ship_ts"])
    effective = max((v for v in po["versions"] if datetime.fromisoformat(v["issued_at"]) < ship_ts),
                    key=lambda v: v["version"])
    received = sum(r["cases"] for r in case["receiving"])
    if received >= effective["ordered_cases"]:
        if fine["po_version_used"] != effective["version"]:
            return "C5", "walmart", 0.0
        return "C4", "walmart", 0.0
    if any(r["exception"] == "SHORT" for r in case["receiving"]):
        short = effective["ordered_cases"] - received
        return "C3", "supplier", round(short * cost * RATE, 2)
    return "HANDOFF", None, None


def main(path):
    data = json.load(open(path))
    failures = 0
    for case in data["cases"]:
        fine, po, exp = case["fine_record"], case["po"], case["expected"]
        problems = []
        system_amount = round(fine["non_compliant_cases"] * po["case_cost"] * RATE, 2)
        if system_amount != fine["amount"]:
            problems.append(f"fine amount {fine['amount']} != recomputed {system_amount}")
        if fine["metric"] == "in_full" and fine["ordered_cases"] - fine["received_cases"] != fine["non_compliant_cases"]:
            problems.append("in-full non-compliant cases do not match ordered - received")
        if fine["metric"] == "on_time" and not d(fine["recorded_arrival"]) > d(po["mabd"]):
            problems.append("on-time fine but recorded arrival is not after MABD")
        if case["dispute"] and case["dispute"]["amount_disputed"] != fine["amount"]:
            problems.append("disputed amount differs from the fine")
        cause, accountable, corrected = derive(case)
        if (cause, accountable, corrected) != (exp["cause"], exp["accountable"], exp["corrected_fine"]):
            problems.append(f"derived {(cause, accountable, corrected)} != expected "
                            f"{(exp['cause'], exp['accountable'], exp['corrected_fine'])}")
        ids = json.dumps(case)
        for ev in exp["key_evidence"]:
            if ids.count(f'"{ev}"') < 2:
                problems.append(f"key evidence {ev} is not a record in the case")
        status = "OK  " if not problems else "FAIL"
        failures += bool(problems)
        print(f"{status} {case['case_id']}  {exp['cause']} {exp['outcome']:6}  "
              f"system fine ${fine['amount']:.2f} -> corrected ${exp['corrected_fine']:.2f}")
        for p in problems:
            print("     -", p)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main(sys.argv[1])
