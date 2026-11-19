"""Read the evidence for one Domain case and project its planned sources."""

from collections.abc import Iterator
from typing import Any
from uuid import UUID

import httpx

from .investigation import Evidence, EvidenceReadError, EvidenceSource


def _record(row: dict[str, Any], *fields: str, **links: Any) -> Evidence:
    record_id = row["id"]
    if not isinstance(record_id, str) or not record_id:
        raise ValueError("Missing evidence record ID")
    return {"record_id": record_id, "facts": {**{field: row[field] for field in fields}, **links}}


def _read_asns(context: dict[str, Any], po_line_id: str) -> list[Evidence]:
    records = []
    for group in context["asns"]:
        asn = group["asn"]
        for line in group["lines"]:
            if line["po_line_id"] == po_line_id and line["asn_id"] == asn["id"]:
                records.append(_record(
                    line, "asn_id", "shipped_cases", asn_number=asn["asn_number"], ship_ts=asn["ship_ts"],
                ))
    return records


def _read_appointments(context: dict[str, Any], po_line_id: str) -> list[Evidence]:
    return [
        _record(row, "event_ts", "appointment_ts", "action", "initiated_by")
        for row in context["appointments"] if row["po_line_id"] == po_line_id
    ]


def _read_po_versions(context: dict[str, Any], po_line_id: str) -> list[Evidence]:
    return [
        _record(row, "version_number", "issued_at", "ordered_cases")
        for row in context["po_line_versions"] if row["po_line_id"] == po_line_id
    ]


def _deliveries(context: dict[str, Any], po_line_id: str) -> Iterator[dict[str, Any]]:
    for group in context["deliveries"]:
        asn_line = group["asn_line"]
        delivery_line = group["delivery_line"]
        if (
            asn_line["po_line_id"] == po_line_id
            and delivery_line["asn_line_id"] == asn_line["id"]
            and delivery_line["delivery_id"] == group["delivery"]["id"]
        ):
            yield group


def _read_gate_logs(context: dict[str, Any], po_line_id: str) -> list[Evidence]:
    records = {}
    for group in _deliveries(context, po_line_id):
        delivery_id = group["delivery"]["id"]
        for row in group["gate_logs"]:
            if row["delivery_id"] == delivery_id:
                records[row["id"]] = _record(row, "delivery_id", "check_in_ts")
    return list(records.values())


def _read_receiving(context: dict[str, Any], po_line_id: str) -> list[Evidence]:
    records = {}
    for group in _deliveries(context, po_line_id):
        delivery_id = group["delivery"]["id"]
        delivery_line_id = group["delivery_line"]["id"]
        for row in group["receiving_records"]:
            if row["delivery_line_id"] == delivery_line_id:
                records[row["id"]] = _record(
                    row, "delivery_line_id", "received_at", "received_cases", "exception_code",
                    delivery_id=delivery_id,
                )
    return list(records.values())


READERS = {
    "asn": _read_asns,
    "appointment_history": _read_appointments,
    "gate_log": _read_gate_logs,
    "po_versions": _read_po_versions,
    "receiving": _read_receiving,
}


class DomainEvidenceReader:
    def __init__(self, client: httpx.Client):
        self.client = client

    def read_evidence(
        self, case_id: str, fine_record_id: str, sources: list[EvidenceSource]
    ) -> dict[EvidenceSource, list[Evidence]]:
        try:
            case_id = str(UUID(case_id))
            fine_record_id = str(UUID(fine_record_id))
        except ValueError as exc:
            raise EvidenceReadError("Case and fine record IDs must be Domain UUIDs") from exc

        try:
            response = self.client.get(
                f"/api/v1/investigation-contexts/{fine_record_id}", params={"case_id": case_id},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise EvidenceReadError(f"Domain evidence request returned HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise EvidenceReadError("Domain evidence request failed") from exc

        try:
            context = response.json()
            po_line_id = context["po_line"]["id"]
            fine = context["fine_record"]
            if fine["id"] != fine_record_id or fine["po_line_id"] != po_line_id:
                raise EvidenceReadError("Domain evidence context does not match the requested fine")
            return {source: READERS[source](context, po_line_id) for source in sources}
        except (KeyError, TypeError, ValueError) as exc:
            raise EvidenceReadError("Domain evidence response has an invalid shape") from exc
