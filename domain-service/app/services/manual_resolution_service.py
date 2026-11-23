"""A reviewer takes over a handed-off Case and decides its cause."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.db.models import CaseOutcome
from app.services.case_service import _lock_case, transition_case
from app.services.evaluation_service import create_evaluation
from app.services.exceptions import Conflict, InvalidRequest
from app.services.finding_service import create_finding
from app.services.outcome_service import create_outcome

# Policy section 3: which causes apply to which fine type.
CAUSES_BY_METRIC = {"on_time": {"C1", "C2"}, "in_full": {"C3", "C4", "C5"}}


def resolve_handoff(
    session: Session, *, case_id: uuid.UUID, cause_code: str, rationale: str, user_id: uuid.UUID,
) -> CaseOutcome:
    """Store the reviewer's finding, run the rules engine and open the approval. Caller owns the transaction.

    The reviewer chooses the cause only. Accountability and amounts still come
    from the rules engine, and the result still needs approval.
    """
    case = _lock_case(session, case_id)
    if case.status != "handed_off":
        raise Conflict("Only a handed-off Case can be resolved by a reviewer")
    allowed = CAUSES_BY_METRIC.get(case.fine_record.metric or "", set())
    if cause_code not in allowed:
        raise InvalidRequest(f"Cause {cause_code} does not apply to a {case.fine_record.metric} fine")
    transition_case(session, case_id=case_id, target="investigating",
                    reason="Taken over by a reviewer", actor_user_id=user_id)
    finding = create_finding(session, case_id=case_id, payload={
        "cause_code": cause_code, "summary": rationale, "submitted_by_user_id": user_id,
    })
    evaluation = create_evaluation(session, case_id=case_id, finding_id=finding.id)
    return create_outcome(session, case_id=case_id, evaluation_id=evaluation.id)
