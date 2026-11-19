"""Append-only Finding persistence and per-Case version assignment."""
from __future__ import annotations

import uuid
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    ASNLine, AppointmentEvent, DeliveryLine, EvidenceLink, EvidenceRecord, FindingFact, GateLog,
    InvestigationCase, InvestigationFinding, POLineVersion, ReceivingRecord,
)
from app.services.exceptions import Conflict, InvalidRequest, NotFound
from app.services.case_service import transition_case
from app.services.context_service import row


SOURCE_QUERIES = {
    "asn": (ASNLine, select(ASNLine), ASNLine.po_line_id),
    "appointment_history": (AppointmentEvent, select(AppointmentEvent), AppointmentEvent.po_line_id),
    "gate_log": (
        GateLog, select(GateLog).join(DeliveryLine, DeliveryLine.delivery_id == GateLog.delivery_id)
        .join_from(DeliveryLine, ASNLine, DeliveryLine.asn_line_id == ASNLine.id), ASNLine.po_line_id,
    ),
    "po_versions": (POLineVersion, select(POLineVersion), POLineVersion.po_line_id),
    "receiving": (
        ReceivingRecord, select(ReceivingRecord).join(DeliveryLine)
        .join_from(DeliveryLine, ASNLine, DeliveryLine.asn_line_id == ASNLine.id), ASNLine.po_line_id,
    ),
}


def record_evidence(session: Session, source: str, record_id: uuid.UUID, po_line_id: uuid.UUID) -> EvidenceRecord:
    model, query, line_column = SOURCE_QUERIES[source]
    record = session.scalars(query.where(model.id == record_id, line_column == po_line_id)).first()
    if record is None:
        raise InvalidRequest("Evidence source does not belong to the Case PO Line")
    evidence = EvidenceRecord(evidence_type=source, external_id=str(record_id), snapshot=row(record))
    session.add(evidence)
    session.flush()
    return evidence


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
        agent_run_id=payload.get("agent_run_id"),
        handoff_required=payload.get("handoff_required", False),
        handoff_reason=payload.get("handoff_reason"),
        injection_detected=payload.get("injection_detected", False),
    )
    session.add(finding)
    session.flush()
    recorded: dict[tuple[str, uuid.UUID], uuid.UUID] = {}
    for fact_data in payload.get("facts", []):
        fact = FindingFact(
            finding_id=finding.id,
            fact_key=fact_data["fact_key"],
            fact_value=fact_data.get("fact_value"),
            source_description=fact_data.get("source_description"),
        )
        session.add(fact)
        session.flush()
        evidence_ids = list(fact_data.get("evidence_ids", []))
        for ref in fact_data.get("source_refs", []):
            key = (ref["source"], ref["record_id"])
            if key not in recorded:
                recorded[key] = record_evidence(session, *key, case.fine_record.po_line_id).id
            evidence_ids.append(recorded[key])
        if len(set(evidence_ids)) != len(evidence_ids):
            raise InvalidRequest("Evidence references must be unique within a Fact")
        for evidence_id in evidence_ids:
            if session.get(EvidenceRecord, evidence_id) is None:
                raise InvalidRequest("Evidence reference does not exist")
            session.add(EvidenceLink(finding_fact_id=fact.id, evidence_record_id=evidence_id, role="supports"))
    session.flush()
    transition_case(session, case_id=case_id, target="findings_submitted", reason="Finding submitted")
    return finding
