"""Serialized line-level approvals; decisions are append-only history."""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Approval, ApprovalDecision, CaseOutcome, InvestigationCase, LineOutcome, PolicyConfiguration
from app.services.case_service import transition_case
from app.services.exceptions import Conflict, InvalidRequest, NotFound


def decide_line(session: Session, *, outcome_id: uuid.UUID, line_outcome_id: uuid.UUID, stage: str, decision: str, auth_user_id: uuid.UUID, comment: str | None = None) -> ApprovalDecision:
    if stage not in {"associate", "manager"} or decision not in {"approved", "rejected"}:
        raise InvalidRequest("Unsupported approval stage or decision")
    line = session.execute(select(LineOutcome).where(LineOutcome.id == line_outcome_id).with_for_update()).scalar_one_or_none()
    if line is None or line.case_outcome_id != outcome_id:
        raise NotFound("Line Outcome was not found for the specified Outcome")
    aggregate = session.get(CaseOutcome, outcome_id)
    case = session.execute(select(InvestigationCase).where(InvestigationCase.id == aggregate.investigation_case_id).with_for_update()).scalar_one()
    approval = session.execute(select(Approval).where(Approval.line_outcome_id == line.id, Approval.approval_type == stage).with_for_update()).scalar_one_or_none()
    if approval is None:
        raise Conflict("Approval stage is not currently available")
    if approval.status != "pending":
        raise Conflict("Approval stage has already been completed")
    if session.scalar(select(ApprovalDecision.id).where(ApprovalDecision.approval_id == approval.id)):
        raise Conflict("Approval already has a recorded decision")
    if stage == "manager":
        associate = session.execute(select(Approval).where(Approval.line_outcome_id == line.id, Approval.approval_type == "associate")).scalar_one_or_none()
        if associate is None or associate.status != "approved":
            raise Conflict("Associate approval is required before Manager approval")
    record = ApprovalDecision(approval_id=approval.id, auth_user_id=auth_user_id, decision=decision, comment=comment)
    session.add(record)
    approval.status = decision
    session.flush()
    if decision == "rejected":
        line.approval_status = "rejected"
        aggregate.status = "rejected"
        if case.status == "awaiting_approval":
            transition_case(session, case_id=case.id, target="revision_required", reason=f"{stage.title()} approval rejected")
        session.flush()
        return record

    if stage == "associate":
        policy_version = aggregate.evaluation.policy_version
        policy = session.get(PolicyConfiguration, policy_version)
        if policy is None:
            raise Conflict("Outcome policy configuration is missing")
        if Decimal(line.reversal_amount) > Decimal(policy.manager_approval_threshold):
            session.add(Approval(line_outcome_id=line.id, approval_type="manager", status="pending"))
            line.approval_status = "pending_manager_approval"
            aggregate.status = "pending_manager_approval"
        else:
            line.approval_status = "approved"
    else:
        line.approval_status = "approved"

    session.flush()
    lines = session.execute(select(LineOutcome).where(LineOutcome.case_outcome_id == outcome_id)).scalars().all()
    if any(item.approval_status == "rejected" for item in lines):
        aggregate.status = "rejected"
    elif any(item.approval_status == "pending_manager_approval" for item in lines):
        aggregate.status = "pending_manager_approval"
    elif any(item.approval_status == "pending_approval" for item in lines):
        aggregate.status = "pending_approval"
    elif lines and all(item.approval_status == "approved" for item in lines):
        aggregate.status = "approved"
        if case.status == "awaiting_approval":
            transition_case(session, case_id=case.id, target="closed")
    session.flush()
    return record
