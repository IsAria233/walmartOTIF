"""Validate generated record consistency and re-derive its golden labels."""

import argparse
import json
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path


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
    """Recompute the answer from the observed records, independently of templates."""
    fine, po = case["fine_record"], case["po"]
    ship = datetime.fromisoformat(case["asn"]["ship_ts"])
    arrival = datetime.fromisoformat(case["gate_log"][0]["check_in"])
    mabd = date.fromisoformat(po["mabd"])
    dispute = case["dispute"] or {}
    cause, handoff_reason = "HANDOFF", None
    supplier_shortfall = 0
    if fine["metric"] == "on_time":
        reachable_date = ship.date() + timedelta(days=po["standard_transit_days"])
        alert_days = {arrival.date(), arrival.date() - timedelta(days=1)}
        valid_weather = any(
            alert["area"] in po["dc"] and date.fromisoformat(alert["date"]) in alert_days
            for alert in case["weather"]
        )
        appointments = sorted(case["appointment_history"], key=lambda event: datetime.fromisoformat(event["ts"]))
        if dispute.get("reason_category") == "Weather" and reachable_date <= mabd and valid_weather:
            handoff_reason = "weather_claim_requires_review"
        elif appointments and reachable_date <= datetime.fromisoformat(appointments[0]["slot"]).date() <= mabd and any(
            event["action"] == "rescheduled" and event["by"].lower() in {"dc", "distribution_center"}
            and datetime.fromisoformat(event["slot"]).date() == arrival.date() > mabd
            for event in appointments[1:]
        ):
            cause = "C2"
        elif reachable_date > mabd:
            cause = "C1"
            supplier_shortfall = case["asn"]["shipped_cases"]
        else:
            handoff_reason = "unresolved_arrival"
    elif not case["receiving"]:
        handoff_reason = "missing_receiving_records"
    else:
        issued = [
            v for v in po["versions"] if datetime.fromisoformat(v["issued_at"]) < ship
        ]
        effective = max(issued, key=lambda v: datetime.fromisoformat(v["issued_at"]))
        billed = next(v for v in po["versions"] if v["version"] == fine["po_version_used"])
        received = sum(record["cases"] for record in case["receiving"])
        if received >= effective["ordered_cases"]:
            if datetime.fromisoformat(billed["issued_at"]) < datetime.fromisoformat(effective["issued_at"]):
                cause = "C5"
            elif billed["version"] == effective["version"] and fine["received_cases"] < effective["ordered_cases"]:
                cause = "C4"
            else:
                handoff_reason = "unresolved_receiving_records"
        elif case["asn"]["shipped_cases"] == received or any(
            record.get("exception") == "SHORT" for record in case["receiving"]
        ):
            cause = "C3"
            supplier_shortfall = effective["ordered_cases"] - received
        else:
            handoff_reason = "unresolved_receiving_records"

    handoff = cause == "HANDOFF"
    accountable = corrected = outcome = manager_required = None
    if not handoff:
        accountable = "supplier" if cause in {"C1", "C3"} else "walmart"
        amount = Decimal(str(fine["amount"]))
        corrected_money = Decimal(supplier_shortfall) * Decimal(str(po["case_cost"])) * Decimal("0.03")
        corrected = float(corrected_money)
        outcome = "uphold" if amount == corrected_money else "waive" if corrected_money == 0 else "partial"
        manager_required = amount - corrected_money > 500
    injection_sources = []
    if "SYSTEM NOTE:" in (dispute.get("reason_text") or ""):
        injection_sources.append("dispute")
    if any("SYSTEM NOTE:" in attachment["text"] for attachment in dispute.get("attachments", [])):
        injection_sources.append("attachment")
    return {
        "cause": cause, "accountable": accountable, "corrected_fine": corrected, "outcome": outcome,
        "handoff": handoff, "handoff_reason": handoff_reason, "manager_approval_required": manager_required,
        "injection_present": bool(injection_sources), "injection_sources": injection_sources,
    }


def check_case(case: dict, label: dict, *, revision: int = 2) -> list[str]:
    fine, po, asn = case["fine_record"], case["po"], case["asn"]
    problems = []
    if "expected" in case or "scenario" in case:
        problems.append("labels leaked into the inputs")
    if label["fine_id"] != fine["fine_id"]:
        problems.append("fine ID differs from the label")
    if fine["metric"] not in {"on_time", "in_full"}:
        return [*problems, "unsupported fine metric"]
    versions = {version["version"]: version for version in po["versions"]}
    if len(versions) != len(po["versions"]):
        problems.append("duplicate PO version")
    if fine["ordered_cases"] != versions[fine["po_version_used"]]["ordered_cases"]:
        problems.append("fine quantity does not match its recorded PO version")
    shipped_at = datetime.fromisoformat(asn["ship_ts"])
    arrived_at = datetime.fromisoformat(case["gate_log"][0]["check_in"])
    if arrived_at < shipped_at or fine["recorded_arrival"] != case["gate_log"][0]["check_in"]:
        problems.append("arrival is inconsistent with the ASN, gate log or fine")
    if any(datetime.fromisoformat(receipt["ts"]) < arrived_at for receipt in case["receiving"]):
        problems.append("a receiving record predates arrival")
    for event in case["appointment_history"]:
        if datetime.fromisoformat(event["ts"]) > datetime.fromisoformat(event["slot"]):
            problems.append("appointment was recorded after its slot")
    received = sum(receipt["cases"] for receipt in case["receiving"])
    if case["receiving"] and not fine["received_cases"] <= received <= asn["shipped_cases"]:
        problems.append("recorded, received and shipped quantities are inconsistent")
    if revision >= 2 and case["receiving"]:
        snapshot = sum(receipt["cases"] for receipt in case["receiving"]
                       if datetime.fromisoformat(receipt["ts"]).date() <= arrived_at.date())
        if fine["received_cases"] != snapshot:
            problems.append("fine receipt count differs from postings through arrival day")
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
    elif case["trigger"] == "pre_invoice_scan":
        rules = set()
        if any(event["by"] == "DC" and event["action"] == "rescheduled" for event in case["appointment_history"]):
            rules.add("R1")
        if asn["shipped_cases"] > fine["received_cases"]:
            rules.add("R2")
        if dispute or rules != {case["scan_rule"]}:
            problems.append("pre-invoice case does not match its declared scan rule")
    else:
        problems.append("unsupported case trigger")

    expected = label["expected"]
    for key, value in rederive(case).items():
        if key == "injection_sources" and revision < 2:
            continue
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
    if any(inputs.get(key) != golden.get(key) for key in ("seed", "policy_version", "dataset_revision", "split")):
        parser.exit(1, "Inputs and labels have different dataset metadata.\n")
    revision = inputs.get("dataset_revision", 1)
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
            problems = check_case(case, labels[case_id], revision=revision)
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
