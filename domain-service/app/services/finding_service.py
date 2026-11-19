"""Append-only Finding persistence and per-Case version assignment."""
from __future__ import annotations

import uuid
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import EvidenceLink, EvidenceRecord, FindingFact, InvestigationCase, InvestigationFinding
from app.services.exceptions import Conflict, InvalidRequest, NotFound
from app.services.case_service import transition_case


def create_finding(session: Session, *, case_id: uuid.UUID, payload: dict) -> InvestigationFinding:
    case = session.execute(select(InvestigationCase).where(InvestigationCase.id == case_id).with_for_update()).scalar_one_or_none()
    if case is None:
        raise NotFound("Investigation Case not found")
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
    for fact_data in payload.get("facts", []):
        fact = FindingFact(
            finding_id=finding.id,
            fact_key=fact_data["fact_key"],
            fact_value=fact_data.get("fact_value"),
            source_description=fact_data.get("source_description"),
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
