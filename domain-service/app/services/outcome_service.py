"""Create a historical aggregate Outcome and independently reviewable lines."""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Approval, CaseOutcome, Evaluation, InvestigationCase, InvestigationFinding, LineOutcome
from app.services.case_service import transition_case
from app.services.exceptions import Conflict, InvalidRequest, NotFound


def create_outcome(
    session: Session, *, case_id: uuid.UUID, evaluation_id: uuid.UUID, reuse_existing: bool = False,
) -> CaseOutcome:
    case = session.execute(select(InvestigationCase).where(InvestigationCase.id == case_id).with_for_update()).scalar_one_or_none()
    if case is None:
        raise NotFound("Investigation Case not found")
    evaluation = session.get(Evaluation, evaluation_id)
    if evaluation is None:
        raise NotFound("Evaluation not found")
    if evaluation.investigation_case_id != case_id:
        raise InvalidRequest("Evaluation belongs to a different Case")
    existing = session.scalar(select(CaseOutcome).where(CaseOutcome.evaluation_id == evaluation_id))
    if existing is not None and reuse_existing:
        return existing
    if case.status != "findings_submitted":
        raise Conflict("Case is not ready for an Outcome")
    if existing is not None:
        raise Conflict("This Evaluation already has an Outcome")
    outcome = CaseOutcome(investigation_case_id=case_id, evaluation_id=evaluation_id, status="pending_approval")
    session.add(outcome)
    session.flush()
    finding = session.get(InvestigationFinding, evaluation.finding_id)
    for index, value in enumerate(evaluation.result.get("lines", [])):
        line_key = value.get("fine_record_id") or f"line-{index + 1}"
        amount = Decimal(value["corrected_amount"])
        original = Decimal(value["original_amount"])
        line = LineOutcome(
            case_outcome_id=outcome.id,
            investigation_case_id=case_id,
            evaluated_line_key=line_key,
            finding_id=finding.id,
            outcome=value["disposition"],
            policy_version=evaluation.policy_version,
            accountable_party=value["accountable_party"],
            original_amount=original,
            corrected_amount=amount,
            reversal_amount=Decimal(value["reversal_amount"]),
            calculated_at=evaluation.evaluated_at,
            approval_status="pending_approval",
            rationale="Deterministic policy result; see Evaluation snapshot.",
        )
        session.add(line)
        session.flush()
        session.add(Approval(line_outcome_id=line.id, approval_type="associate", status="pending"))
    session.flush()
    transition_case(session, case_id=case_id, target="awaiting_approval")
    return outcome
