"""Shared Investigation Case creation, reuse, association and lifecycle rules."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    CaseOutcome, CaseStatusEvent, Dispute, DisputeLine, DisputeLineCase, FineRecord,
    InvestigationCase, InvestigationFinding, LineOutcome, POLine, PurchaseOrder,
)
from app.services.exceptions import Conflict, InvalidRequest, NotFound

TRANSITIONS = {
    "pending": {"investigating"},
    "investigating": {"findings_submitted", "handed_off"},
    "findings_submitted": {"awaiting_approval"},
    "awaiting_approval": {"closed", "revision_required"},
    "revision_required": {"investigating"},
    "handed_off": {"investigating"},
    "closed": set(),
}


def get_or_create_active_case(
    session: Session,
    *,
    fine_record_id: uuid.UUID,
    origin: str,
    scan_rule: str | None = None,
    dispute_line_ids: list[uuid.UUID] | None = None,
) -> tuple[InvestigationCase, bool]:
    """Lock a Fine Record, reuse its active Case, or create one; caller owns txn."""
    fine = session.execute(
        select(FineRecord).where(FineRecord.id == fine_record_id).with_for_update()
    ).scalar_one_or_none()
    if fine is None:
        raise NotFound("Fine Record not found")
    if origin not in {"supplier_dispute", "pre_invoice_scan"}:
        raise InvalidRequest("Unsupported Case origin")
    if origin == "supplier_dispute" and not dispute_line_ids:
        raise InvalidRequest("Supplier-dispute Case requires at least one Dispute Line")
    if scan_rule is not None and origin != "pre_invoice_scan":
        raise InvalidRequest("scan_rule is only valid for pre-invoice Cases")
    if len(set(dispute_line_ids or [])) != len(dispute_line_ids or []):
        raise InvalidRequest("Dispute Line IDs must be unique")
    validated_lines = {}
    for line_id in dispute_line_ids or []:
        line_and_dispute = session.execute(
            select(DisputeLine, Dispute)
            .join(Dispute, Dispute.id == DisputeLine.dispute_id)
            .where(DisputeLine.id == line_id)
            .with_for_update()
        ).one_or_none()
        if line_and_dispute is None:
            raise InvalidRequest("Dispute Line was not found")
        line, dispute = line_and_dispute
        if line.fine_record_id != fine_record_id:
            raise InvalidRequest("Dispute Line must belong to the Fine Record")
        fine_supplier_id = session.scalar(
            select(PurchaseOrder.supplier_id)
            .join(POLine, POLine.purchase_order_id == PurchaseOrder.id)
            .where(POLine.id == fine.po_line_id)
        )
        if dispute.supplier_id != fine_supplier_id:
            raise InvalidRequest("Dispute Line supplier must match Fine Record supplier")
        validated_lines[line_id] = line
    if origin == "pre_invoice_scan" and scan_rule not in {None, "R1", "R2"}:
        raise InvalidRequest("Unsupported pre-invoice scan rule")
    active = session.execute(
        select(InvestigationCase)
        .where(InvestigationCase.fine_record_id == fine_record_id, InvestigationCase.status != "closed")
        .with_for_update()
    ).scalar_one_or_none()
    created = active is None
    if active is None:
        ids = dispute_line_ids or []
        first_line = None
        if origin == "supplier_dispute" and ids:
            first_line = validated_lines[ids[0]]
        active = InvestigationCase(
            fine_record_id=fine_record_id,
            origin=origin,
            scan_rule=scan_rule,
            dispute_line_id=first_line.id if first_line else None,
            status="pending",
        )
        try:
            with session.begin_nested():
                session.add(active)
                session.flush()
                session.add(CaseStatusEvent(
                    investigation_case_id=active.id,
                    from_status=None,
                    to_status="pending",
                    reason="Case created",
                ))
                session.flush()
        except IntegrityError as exc:
            # The partial index is the final backstop, including writers that
            # did not take the Fine Record lock. Savepoint rollback preserves
            # the caller's encompassing transaction before looking up winner.
            active = session.execute(select(InvestigationCase).where(
                InvestigationCase.fine_record_id == fine_record_id,
                InvestigationCase.status != "closed",
            ).with_for_update()).scalar_one_or_none()
            constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            is_active_case_conflict = (
                constraint_name == "uq_active_case_per_fine"
                or "investigation_cases.fine_record_id" in str(exc.orig)
            )
            if active is None or not is_active_case_conflict:
                if not is_active_case_conflict:
                    raise
                raise Conflict("An Active Case already exists for this Fine Record") from exc
            created = False
    for line_id in dispute_line_ids or []:
        line = validated_lines[line_id]
        exists = session.scalar(select(DisputeLineCase.id).where(
            DisputeLineCase.dispute_line_id == line_id,
            DisputeLineCase.investigation_case_id == active.id,
        ))
        if exists is None:
            session.add(DisputeLineCase(
                dispute_line_id=line_id,
                investigation_case_id=active.id,
                fine_record_id=fine_record_id,
            ))
    session.flush()
    return active, created


def _lock_case(session: Session, case_id: uuid.UUID) -> InvestigationCase:
    case = session.execute(
        select(InvestigationCase).where(InvestigationCase.id == case_id).with_for_update()
    ).scalar_one_or_none()
    if case is None:
        raise NotFound("Investigation Case not found")
    return case


def _append_status_event(
    session: Session, case: InvestigationCase, target: str, *, reason: str | None,
    actor_user_id: uuid.UUID | None = None, agent_run_id: uuid.UUID | None = None,
    handoff_details: dict | None = None,
) -> CaseStatusEvent:
    event = CaseStatusEvent(
        investigation_case_id=case.id, from_status=case.status, to_status=target, reason=reason,
        actor_user_id=actor_user_id, agent_run_id=agent_run_id, handoff_details=handoff_details,
    )
    case.status = target
    session.add(event)
    session.flush()
    return event


def transition_case(session: Session, *, case_id: uuid.UUID, target: str, reason: str | None = None, actor_user_id: uuid.UUID | None = None) -> InvestigationCase:
    case = _lock_case(session, case_id)
    if target not in TRANSITIONS.get(case.status, set()):
        raise Conflict(f"Case transition from {case.status} to {target} is not allowed")
    if target == "findings_submitted" and not case.findings:
        raise Conflict("A Finding is required before findings_submitted")
    if target == "awaiting_approval":
        if not case.evaluations or not case.outcomes:
            raise Conflict("A valid Evaluation and Outcome are required before approval")
    if target == "closed":
        current = max(case.outcomes, key=lambda outcome: outcome.created_at, default=None)
        if current is None or not current.line_outcomes:
            raise Conflict("At least one applicable Line Outcome is required to close a Case")
        if any(line.approval_status != "approved" for line in current.line_outcomes):
            raise Conflict("Every Line Outcome in the current Outcome must be approved")
    _append_status_event(session, case, target, reason=reason, actor_user_id=actor_user_id)
    return case


def record_agent_handoff(
    session: Session, *, case_id: uuid.UUID, run_id: uuid.UUID, reason: str, details: dict,
) -> CaseStatusEvent:
    case = _lock_case(session, case_id)
    existing = session.scalar(select(CaseStatusEvent).where(
        CaseStatusEvent.investigation_case_id == case_id, CaseStatusEvent.agent_run_id == run_id,
    ))
    if existing is not None:
        return existing

    finding_id = details.get("finding_id")
    if case.status == "findings_submitted":
        latest = session.scalar(select(InvestigationFinding).where(
            InvestigationFinding.investigation_case_id == case_id,
        ).order_by(InvestigationFinding.version_number.desc()).limit(1))
        if latest is None or str(latest.id) != finding_id or latest.agent_run_id != run_id:
            raise Conflict("Handoff must reference the latest Finding from this Agent run")
    elif finding_id is not None or case.status not in {"pending", "investigating", "revision_required", "handed_off"}:
        raise Conflict(f"Case status {case.status} does not allow this handoff")

    return _append_status_event(
        session, case, "handed_off", reason=reason, agent_run_id=run_id, handoff_details=details,
    )


def current_handoff(session: Session, case: InvestigationCase) -> CaseStatusEvent | None:
    if case.status != "handed_off":
        return None
    return session.scalar(select(CaseStatusEvent).where(
        CaseStatusEvent.investigation_case_id == case.id, CaseStatusEvent.to_status == "handed_off",
    ).order_by(CaseStatusEvent.occurred_at.desc(), CaseStatusEvent.id.desc()).limit(1))


def mark_case_revision_required(session: Session, case_id: uuid.UUID) -> None:
    case = session.execute(select(InvestigationCase).where(InvestigationCase.id == case_id).with_for_update()).scalar_one()
    if case.status == "awaiting_approval":
        transition_case(session, case_id=case_id, target="revision_required", reason="Approval rejected")
