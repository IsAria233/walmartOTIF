"""Evaluation version assignment and immutable policy snapshots."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Evaluation, InvestigationCase, InvestigationFinding, PolicyConfiguration
from app.services.exceptions import Conflict, InvalidRequest, NotFound, PolicyUnavailable
from app.services.policy_evaluator import evaluate_line


def create_evaluation(
    session: Session, *, case_id: uuid.UUID, finding_id: uuid.UUID, reuse_existing: bool = False,
) -> Evaluation:
    case = session.execute(
        select(InvestigationCase).where(InvestigationCase.id == case_id).with_for_update()
    ).unique().scalar_one_or_none()
    if case is None:
        raise NotFound("Investigation Case not found")
    if reuse_existing:
        existing = session.scalar(select(Evaluation).where(
            Evaluation.investigation_case_id == case_id,
            Evaluation.finding_id == finding_id,
        ).order_by(Evaluation.version_number.desc()).limit(1))
        if existing is not None:
            return existing
    if case.status not in {"findings_submitted", "revision_required"}:
        raise Conflict("Case must have submitted findings or require revision before evaluation")
    finding = session.get(InvestigationFinding, finding_id)
    if finding is None:
        raise NotFound("Finding not found")
    if finding.investigation_case_id != case_id:
        raise InvalidRequest("Finding belongs to a different Case")
    now = datetime.now(timezone.utc)
    policy = session.execute(
        select(PolicyConfiguration)
        .where(PolicyConfiguration.effective_from <= now)
        .order_by(PolicyConfiguration.effective_from.desc(), PolicyConfiguration.policy_version.desc())
        .limit(1)
        .with_for_update()
    ).scalar_one_or_none()
    if policy is None:
        raise PolicyUnavailable("No applicable policy configuration is available")
    result = evaluate_line(case.fine_record, finding, policy)
    version = (session.scalar(select(func.max(Evaluation.version_number)).where(Evaluation.investigation_case_id == case_id)) or 0) + 1
    evaluation = Evaluation(
        investigation_case_id=case_id,
        finding_id=finding_id,
        version_number=version,
        policy_version=policy.policy_version,
        evaluated_at=now,
        result={"lines": [result]},
        calculation_inputs={
            "fine_record_id": str(case.fine_record_id),
            "non_compliant_cases": case.fine_record.non_compliant_cases,
            "case_cost": str(case.fine_record.case_cost_snapshot),
            "original_amount": str(case.fine_record.original_amount),
            "policy_fine_rate": str(policy.fine_rate),
            "accountable_party": result["accountable_party"],
            "finding_id": str(finding_id),
        },
        calculation_outputs={"lines": [result]},
    )
    session.add(evaluation)
    session.flush()
    return evaluation
