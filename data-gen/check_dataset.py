"""Validate generated record consistency and re-derive its golden labels."""

import argparse
import json
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from seed_cases.check_seed_cases import derive


def record_ids(case: dict) -> set[str]:
    fields = {
        "po_number", "version_id", "asn_id", "event_id", "gate_id",
        "receipt_id", "alert_id", "fine_id", "dispute_id", "attachment_id",
    }
    ids = {case["po"]["po_number"], case["asn"]["asn_id"], case["fine_record"]["fine_id"]}
    records = [
        *case["po"]["versions"], *case["appointment_history"], *case["gate_log"],
        *case["receiving"], *case["weather"],
    ]
    if case["dispute"]:
        records.extend([case["dispute"], *case["dispute"]["attachments"]])
    ids.update(value for record in records for key, value in record.items() if key in fields)
    return ids


def rederive(case: dict) -> dict:
    """Use observed records and the existing seed checker, independent of templates."""
    fine, po = case["fine_record"], case["po"]
    ship = datetime.fromisoformat(case["asn"]["ship_ts"])
    arrival = datetime.fromisoformat(case["gate_log"][0]["check_in"])
    mabd = date.fromisoformat(po["mabd"])
    dispute = case["dispute"] or {}
    handoff_reason = None
    if fine["metric"] == "in_full" and not case["receiving"]:
        handoff_reason = "missing_receiving_records"
    elif (
        fine["metric"] == "on_time" and dispute.get("reason_category") == "Weather"
        and ship.date() + timedelta(days=po["standard_transit_days"]) <= mabd < arrival.date()
        and any(
            alert["area"] in po["dc"] and date.fromisoformat(alert["date"])
            in {arrival.date(), arrival.date() - timedelta(days=1)}
            for alert in case["weather"]
        )
    ):
        handoff_reason = "weather_claim_requires_review"

    cause, accountable, corrected = ("HANDOFF", None, None) if handoff_reason else derive(case)
    handoff = cause == "HANDOFF"
    outcome = manager_required = None
    if corrected is not None:
        amount = Decimal(str(fine["amount"]))
        corrected_money = Decimal(str(corrected))
        outcome = "uphold" if amount == corrected_money else "waive" if corrected_money == 0 else "partial"
        manager_required = amount - corrected_money > 500
    return {
        "cause": cause, "accountable": accountable, "corrected_fine": corrected, "outcome": outcome,
        "handoff": handoff, "handoff_reason": handoff_reason, "manager_approval_required": manager_required,
        "injection_present": "SYSTEM NOTE:" in dispute.get("reason_text", ""),
    }


def check_case(case: dict, label: dict) -> list[str]:
    fine, po, asn = case["fine_record"], case["po"], case["asn"]
    problems = []
    if "expected" in case or "scenario" in case:
        problems.append("labels leaked into the inputs")
    if label["fine_id"] != fine["fine_id"]:
        problems.append("fine ID differs from the label")
    versions = {version["version"]: version for version in po["versions"]}
    if fine["ordered_cases"] != versions[fine["po_version_used"]]["ordered_cases"]:
        problems.append("fine quantity does not match its recorded PO version")
    shipped_at = datetime.fromisoformat(asn["ship_ts"])
    arrived_at = datetime.fromisoformat(case["gate_log"][0]["check_in"])
    if arrived_at < shipped_at or fine["recorded_arrival"] != case["gate_log"][0]["check_in"]:
        problems.append("arrival is inconsistent with the ASN, gate log or fine")
    if any(datetime.fromisoformat(receipt["ts"]) < arrived_at for receipt in case["receiving"]):
        problems.append("a receiving record predates arrival")
    received = sum(receipt["cases"] for receipt in case["receiving"])
    if case["receiving"] and not fine["received_cases"] <= received <= asn["shipped_cases"]:
        problems.append("recorded, received and shipped quantities are inconsistent")
    non_compliant = asn["shipped_cases"] if fine["metric"] == "on_time" else fine["ordered_cases"] - fine["received_cases"]
    if non_compliant <= 0 or fine["non_compliant_cases"] != non_compliant:
        problems.append("incorrect non-compliant quantity")
    expected_amount = Decimal(non_compliant) * Decimal(str(po["case_cost"])) * Decimal("0.03")
    if expected_amount != Decimal(str(fine["amount"])):
        problems.append("system fine does not match its recorded quantities")
    if fine["metric"] == "on_time" and arrived_at.date() <= date.fromisoformat(po["mabd"]):
        problems.append("on-time fine has no late arrival")

    dispute = case["dispute"]
    if case["trigger"] == "supplier_dispute":
        if not dispute or Decimal(str(dispute["amount_disputed"])) != expected_amount:
            problems.append("supplier dispute is missing or has the wrong amount")
    else:
        rules = set()
        if any(event["by"] == "DC" and event["action"] == "rescheduled" for event in case["appointment_history"]):
            rules.add("R1")
        if asn["shipped_cases"] > fine["received_cases"]:
            rules.add("R2")
        if dispute or rules != {case["scan_rule"]}:
            problems.append("pre-invoice case does not match its declared scan rule")

    expected = label["expected"]
    for key, value in rederive(case).items():
        if expected[key] != value:
            problems.append(f"{key}: expected {expected[key]!r}, derived {value!r}")
    evidence = expected["key_evidence"]
    if not evidence or set(evidence) - record_ids(case) or len(evidence) != len(set(evidence)):
        problems.append("key evidence is empty, duplicated or does not refer to actual records")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_dir", nargs="?", type=Path, default=Path(__file__).with_name("dataset"))
    args = parser.parse_args()
    inputs = json.loads((args.dataset_dir / "cases.json").read_text(encoding="utf-8"))
    golden = json.loads((args.dataset_dir / "expected.json").read_text(encoding="utf-8"))
    if any(inputs[key] != golden[key] for key in ("seed", "policy_version")):
        parser.exit(1, "Inputs and labels have different dataset metadata.\n")
    cases = {case["case_id"]: case for case in inputs["cases"]}
    labels = {case["case_id"]: case for case in golden["cases"]}
    if not cases or cases.keys() != labels.keys() or len(cases) != len(inputs["cases"]) or len(labels) != len(golden["cases"]):
        parser.exit(1, "Inputs and labels must have matching, unique case IDs.\n")
    for key, values in (
        ("fine", [case["fine_record"]["fine_id"] for case in cases.values()]),
        ("PO", [case["po"]["po_number"] for case in cases.values()]),
        ("ASN", [case["asn"]["asn_id"] for case in cases.values()]),
    ):
        if len(set(values)) != len(cases):
            parser.exit(1, f"Dataset contains duplicate {key} IDs.\n")

    failures = 0
    for case_id, case in cases.items():
        try:
            problems = check_case(case, labels[case_id])
        except (KeyError, TypeError, ValueError) as error:
            problems = [f"invalid case format: {error}"]
        for problem in problems:
            print(f"{case_id}: {problem}")
        failures += bool(problems)
    if failures:
        parser.exit(1, f"{failures} cases failed validation.\n")
    counts = Counter(label["expected"]["cause"] for label in labels.values())
    print(f"Validated {len(cases)} cases: " + ", ".join(f"{cause}={count}" for cause, count in sorted(counts.items())))


if __name__ == "__main__":
    main()
