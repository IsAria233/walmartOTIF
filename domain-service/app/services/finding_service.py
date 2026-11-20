"""Append-only Finding persistence and per-Case version assignment."""
from __future__ import annotations

import uuid
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    ASN, ASNLine, AppointmentEvent, Attachment, Delivery, Dispute, EvidenceLink, EvidenceRecord,
    FindingFact, FineRecord, GateLog, InvestigationCase, InvestigationFinding, POLine,
    POLineVersion, ReceivingRecord, WeatherAlert,
)
from app.services.exceptions import Conflict, InvalidRequest, NotFound
from app.services.case_service import transition_case


# Source records an agent may cite directly as evidence for a fact.
SOURCE_RECORD_MODELS = {
    "fine_record": FineRecord,
    "po_line": POLine,
    "po_line_version": POLineVersion,
    "asn": ASN,
    "asn_line": ASNLine,
    "appointment_event": AppointmentEvent,
    "delivery": Delivery,
    "gate_log": GateLog,
    "receiving_record": ReceivingRecord,
    "weather_alert": WeatherAlert,
    "dispute": Dispute,
    "attachment": Attachment,
}


def _validated_source_records(session: Session, refs: list[dict]) -> list[dict]:
    """Check every cited record exists, so a finding cannot cite invented evidence."""
    result, seen = [], set()
    for ref in refs:
        record_type, record_id = ref["record_type"], ref["record_id"]
        model = SOURCE_RECORD_MODELS.get(record_type)
        if model is None:
            raise InvalidRequest(f"Unsupported source record type: {record_type}")
        if not isinstance(record_id, uuid.UUID):
            try:
                record_id = uuid.UUID(str(record_id))
            except ValueError as exc:
                raise InvalidRequest("Source record id must be a UUID") from exc
        if (record_type, record_id) in seen:
            raise InvalidRequest("Source record references must be unique within a Fact")
        seen.add((record_type, record_id))
        if session.get(model, record_id) is None:
            raise InvalidRequest(f"Source record does not exist: {record_type} {record_id}")
        result.append({"record_type": record_type, "record_id": str(record_id)})
    return result


def create_finding(session: Session, *, case_id: uuid.UUID, payload: dict) -> InvestigationFinding:
    case = session.execute(select(InvestigationCase).where(InvestigationCase.id == case_id).with_for_update()).scalar_one_or_none()
    if case is None:
        raise NotFound("Investigation Case not found")
    run_id = payload.get("agent_run_id")
    if run_id is not None:
        existing = session.scalar(select(InvestigationFinding).where(
            InvestigationFinding.investigation_case_id == case_id,
            InvestigationFinding.agent_run_id == run_id,
        ).order_by(InvestigationFinding.version_number.desc()).limit(1))
        if existing is not None:
            return existing
    if case.status != "investigating":
        raise Conflict("Findings can only be submitted while a Case is investigating")
    version = (session.scalar(select(func.max(InvestigationFinding.version_number)).where(InvestigationFinding.investigation_case_id == case_id)) or 0) + 1
    finding = InvestigationFinding(
        investigation_case_id=case_id,
        version_number=version,
        cause_code=payload.get("cause_code"),
        summary=payload.get("summary"),
        confidence=payload.get("confidence"),
        confidence_level=payload.get("confidence_level"),
        ruled_out_causes=payload.get("ruled_out_causes") or None,
        agent_run_id=payload.get("agent_run_id"),
        handoff_required=payload.get("handoff_required", False),
        handoff_reason=payload.get("handoff_reason"),
        injection_detected=payload.get("injection_detected", False),
    )
    session.add(finding)
    session.flush()
    for fact_data in payload.get("facts", []):
        fact = FindingFact(
            finding_id=finding.id,
            fact_key=fact_data["fact_key"],
            fact_value=fact_data.get("fact_value"),
            source_description=fact_data.get("source_description"),
            source_records=_validated_source_records(session, fact_data.get("source_records") or []) or None,
        )
        session.add(fact)
        session.flush()
        evidence_ids = fact_data.get("evidence_ids", [])
        if len(set(evidence_ids)) != len(evidence_ids):
            raise InvalidRequest("Evidence references must be unique within a Fact")
        for evidence_id in evidence_ids:
            if session.get(EvidenceRecord, evidence_id) is None:
                raise InvalidRequest("Evidence reference does not exist")
            session.add(EvidenceLink(finding_fact_id=fact.id, evidence_record_id=evidence_id, role="supports"))
    session.flush()
    transition_case(session, case_id=case_id, target="findings_submitted", reason="Finding submitted")
    return finding
