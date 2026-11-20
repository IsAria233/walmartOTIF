"""Load the hand-written seed cases into the Domain database.

Usage (from domain-service/, with DATABASE_URL set and migrations applied):

    python -m scripts.load_seed_cases ../data-gen/seed_cases/seed_cases.json

Each case becomes: supplier, DC, PO, PO line and versions, ASN, delivery, gate log,
receiving records, appointment events, weather alerts and a fine record. A supplier
dispute (with text attachments) or a pre-invoice scan then opens the investigation case.

The "expected" block of each case is never loaded: answers stay out of the database.
Seed timestamps have no time zone and are stored as UTC. Running the script twice
skips cases whose fine record already exists.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ASN, ASNLine, AppointmentEvent, Delivery, DeliveryLine, DistributionCenter, FineRecord,
    GateLog, POLine, POLineVersion, PolicyConfiguration, PurchaseOrder, ReceivingRecord,
    Supplier, WeatherAlert,
)
from app.services import run_scan, submit_dispute

FINE_RATE = Decimal("0.03")


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def day(value: str) -> datetime:
    return datetime.combine(date.fromisoformat(value), datetime.min.time(), tzinfo=timezone.utc)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def tagged(external_id: str, note: str | None) -> str:
    """Keep the seed record id (for example RCV-70013) readable on rows without an id column."""
    return f"[{external_id}] {note}".strip() if note else f"[{external_id}]"


def get_or_create(session: Session, model, lookup: dict, **values):
    found = session.execute(select(model).filter_by(**lookup)).scalar_one_or_none()
    if found is not None:
        return found
    row = model(**lookup, **values)
    session.add(row)
    session.flush()
    return row


def ensure_policy(session: Session) -> None:
    if session.execute(select(PolicyConfiguration).limit(1)).scalar_one_or_none() is None:
        session.add(PolicyConfiguration(
            policy_version="0.1", effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            manager_approval_threshold=Decimal("500.00"), fine_rate=FINE_RATE,
        ))
        session.flush()


def load_case(session: Session, case: dict) -> str:
    fine_in = case["fine_record"]
    if session.execute(select(FineRecord.id).where(FineRecord.external_fine_id == fine_in["fine_id"])).scalar_one_or_none():
        return "skipped (already loaded)"

    po_in, asn_in = case["po"], case["asn"]
    supplier = get_or_create(session, Supplier, {"supplier_code": slug(po_in["supplier"])}, name=po_in["supplier"])
    dc_match = re.match(r"DC (\d+)(?: \((.+)\))?", po_in["dc"])
    dc = get_or_create(
        session, DistributionCenter, {"dc_code": dc_match.group(1) if dc_match else slug(po_in["dc"])},
        name=po_in["dc"], region=dc_match.group(2) if dc_match else None,
        country_code="US",  # every seed DC is a Walmart U.S. DC (policy section 1)
    )
    order = get_or_create(
        session, PurchaseOrder, {"po_number": po_in["po_number"]},
        supplier_id=supplier.id, distribution_center_id=dc.id,
        freight_terms=po_in.get("freight_terms"), channel=po_in.get("channel"),
    )
    line = POLine(
        purchase_order_id=order.id, line_number=po_in["line"], item_description=po_in.get("item"),
        mabd=date.fromisoformat(po_in["mabd"]), standard_transit_days=po_in["standard_transit_days"],
        case_cost=Decimal(str(po_in["case_cost"])),
    )
    session.add(line)
    session.flush()

    versions = {}
    for item in po_in["versions"]:
        version = POLineVersion(
            po_line_id=line.id, version_number=item["version"], ordered_cases=item["ordered_cases"],
            issued_at=ts(item["issued_at"]), issued_by=item.get("issued_by"), note=item.get("note"),
        )
        session.add(version)
        versions[item["version"]] = version
    session.flush()

    asn = ASN(asn_number=asn_in["asn_id"], ship_ts=ts(asn_in["ship_ts"]))
    session.add(asn)
    session.flush()
    asn_line = ASNLine(asn_id=asn.id, po_line_id=line.id, shipped_cases=asn_in["shipped_cases"])
    session.add(asn_line)
    session.flush()

    gate = case["gate_log"][0]
    delivery = Delivery(
        distribution_center_id=dc.id, delivery_number=f"DLV-{po_in['po_number']}-{po_in['line']}",
        carrier=gate.get("carrier"), trailer_number=gate.get("trailer"), actual_arrival_ts=ts(gate["check_in"]),
    )
    session.add(delivery)
    session.flush()
    delivery_line = DeliveryLine(asn_line_id=asn_line.id, delivery_id=delivery.id, allocated_cases=asn_in["shipped_cases"])
    session.add(delivery_line)
    session.flush()

    for item in case["gate_log"]:
        session.add(GateLog(delivery_id=delivery.id, check_in_ts=ts(item["check_in"]), gate_identifier=item["gate_id"]))
    for item in case["receiving"]:
        session.add(ReceivingRecord(
            delivery_line_id=delivery_line.id, received_at=ts(item["ts"]), received_cases=item["cases"],
            exception_code=item.get("exception"), note=tagged(item["receipt_id"], item.get("note")),
        ))
    for item in case["appointment_history"]:
        session.add(AppointmentEvent(
            po_line_id=line.id, event_ts=ts(item["ts"]), action=item["action"],
            initiated_by=item["by"].lower(), appointment_ts=ts(item["slot"]),
            note=tagged(item["event_id"], item.get("note")),
        ))
    for item in case.get("weather", []):
        get_or_create(
            session, WeatherAlert, {"external_alert_id": item["alert_id"]},
            distribution_center_id=dc.id, alert_date=date.fromisoformat(item["date"]),
            area=item.get("area"), alert_type=item["type"],
        )

    fine = FineRecord(
        external_fine_id=fine_in["fine_id"], po_line_id=line.id,
        po_line_version_id=versions[fine_in["po_version_used"]].id, po_version_used=fine_in["po_version_used"],
        ordered_cases=fine_in["ordered_cases"], received_cases=fine_in["received_cases"],
        non_compliant_cases=fine_in["non_compliant_cases"], system_accountability=fine_in["system_accountability"],
        metric=fine_in["metric"], original_amount=Decimal(str(fine_in["amount"])),
        case_cost_snapshot=Decimal(str(po_in["case_cost"])), fine_rate=FINE_RATE,
        recorded_arrival_ts=ts(fine_in["recorded_arrival"]), status=fine_in.get("status", "invoiced"),
    )
    session.add(fine)
    session.flush()

    dispute_in = case.get("dispute")
    if dispute_in:
        submit_dispute(
            session, supplier_id=supplier.id,
            lines=[{"fine_record_id": fine.id, "amount_disputed": Decimal(str(dispute_in["amount_disputed"]))}],
            attachments=[{
                "fine_record_id": fine.id, "external_attachment_id": item["attachment_id"],
                "attachment_type": item["type"], "filename": item["filename"], "content_text": item["text"],
            } for item in dispute_in.get("attachments", [])],
            external_dispute_id=dispute_in["dispute_id"], reason_category=dispute_in.get("reason_category"),
            reason_text=dispute_in.get("reason_text"),
            amount_disputed=Decimal(str(dispute_in["amount_disputed"])), submitted_at=day(dispute_in["submitted"]),
        )
        return "loaded (supplier dispute)"
    result = run_scan(session, scan_id=f"seed-{case['case_id']}", fine_record_ids=[fine.id])
    rules = result[0]["triggered_rules"] if result else []
    return f"loaded (pre-invoice scan, rules {rules})"


def main(path: str) -> int:
    from app.db.session import SessionLocal

    if SessionLocal is None:
        print("DATABASE_URL must be set", file=sys.stderr)
        return 2
    cases = json.load(open(path, encoding="utf-8"))["cases"]
    for case in cases:
        with SessionLocal() as session, session.begin():
            ensure_policy(session)
            print(case["case_id"], load_case(session, case))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "../data-gen/seed_cases/seed_cases.json"))
