"""Documented R1/R2 pre-invoice flags, Case reuse and idempotent triggers."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AppointmentEvent, FineRecord, InvestigationCase, InvestigationCaseTrigger, POLine, ASNLine, PreInvoiceScanResult
from app.services.case_service import get_or_create_active_case
from app.services.exceptions import InvalidRequest


def run_scan(session: Session, *, scan_id: str, fine_record_ids: list[UUID] | None = None) -> list[dict]:
    if not scan_id or len(scan_id) > 150 or scan_id == "legacy-unknown":
        raise InvalidRequest("scan_id must contain 1 to 150 characters")
    stmt = select(FineRecord, POLine).join(POLine, POLine.id == FineRecord.po_line_id).order_by(FineRecord.id).with_for_update()
    if fine_record_ids is not None:
        stmt = stmt.where(FineRecord.id.in_(fine_record_ids))
    records = session.execute(stmt).all()
    results = []
    for fine, po_line in records:
        prior_result = session.execute(select(PreInvoiceScanResult).where(
            PreInvoiceScanResult.scan_id == scan_id,
            PreInvoiceScanResult.fine_record_id == fine.id,
        )).scalar_one_or_none()
        if prior_result is not None:
            results.append({
                "fine_record_id": str(fine.id),
                "triggered_rules": prior_result.triggered_rules,
                "rule_results": prior_result.rule_results,
                "failed_rules": [item for item in prior_result.rule_results if item.get("status") == "failed"],
                "case_id": str(prior_result.investigation_case_id) if prior_result.investigation_case_id else None,
                "case_action": prior_result.case_action,
            })
            continue
        events = session.execute(select(AppointmentEvent).where(AppointmentEvent.po_line_id == po_line.id)).scalars().all()
        dc_actions = [event.action.strip().lower() for event in events
                      if (event.initiated_by or "").strip().lower() in {"dc", "distribution_center"}]
        # These are the action values used by the seed-case appointment
        # histories. Unrecognized values remain explicit R1 failures.
        known_changes = {"rescheduled"}
        known_non_changes = {"created"}
        unknown_dc_actions = [action for action in dc_actions if action not in known_changes | known_non_changes]
        r1 = None if unknown_dc_actions else any(action in known_changes for action in dc_actions)
        shipped = session.scalar(select(func.coalesce(func.sum(ASNLine.shipped_cases), 0)).where(ASNLine.po_line_id == po_line.id)) or 0
        r2 = shipped > fine.received_cases
        rules = [rule for rule, triggered in (("R1", r1 is True), ("R2", r2)) if triggered]
        rule_results = [
            {"rule": "R1", "status": "failed", "reason": "unrecognized DC appointment action"} if unknown_dc_actions
            else {"rule": "R1", "status": "triggered" if r1 else "not_triggered"},
            {"rule": "R2", "status": "triggered" if r2 else "not_triggered"},
        ]
        previous_triggers = session.execute(select(InvestigationCaseTrigger).where(
            InvestigationCaseTrigger.scan_id == scan_id,
            InvestigationCaseTrigger.fine_record_id == fine.id,
        ).order_by(InvestigationCaseTrigger.trigger_rule)).scalars().all()
        if previous_triggers:
            previous_case = session.get(InvestigationCase, previous_triggers[0].investigation_case_id)
            previous_rules = sorted({item.trigger_rule for item in previous_triggers})
            results.append({"fine_record_id": str(fine.id), "triggered_rules": previous_rules,
                "rule_results": [{"rule": rule, "status": "triggered", "already_recorded": True} for rule in previous_rules],
                "failed_rules": [], "case_id": str(previous_case.id), "case_action": "reused_existing"})
            continue
        if not rules:
            result = {"fine_record_id": str(fine.id), "triggered_rules": [],
                "rule_results": rule_results,
                "failed_rules": [item for item in rule_results if item["status"] == "failed"],
                "case_id": None, "case_action": "skipped"}
            session.add(PreInvoiceScanResult(scan_id=scan_id, fine_record_id=fine.id,
                triggered_rules=[], rule_results=rule_results, case_action="skipped"))
            session.flush()
            results.append(result)
            continue
        case, created = get_or_create_active_case(session, fine_record_id=fine.id, origin="pre_invoice_scan")
        for rule in rules:
            exists = session.scalar(select(InvestigationCaseTrigger.id).where(
                InvestigationCaseTrigger.investigation_case_id == case.id,
                InvestigationCaseTrigger.fine_record_id == fine.id,
                InvestigationCaseTrigger.trigger_rule == rule,
                InvestigationCaseTrigger.scan_id == scan_id,
            ))
            if exists is None:
                session.add(InvestigationCaseTrigger(investigation_case_id=case.id, fine_record_id=fine.id, trigger_rule=rule, scan_id=scan_id))
        session.flush()
        result = {
            "fine_record_id": str(fine.id),
            "triggered_rules": rules,
            "rule_results": rule_results,
            "failed_rules": [item for item in rule_results if item["status"] == "failed"],
            "case_id": str(case.id),
            "case_action": "created" if created else "reused_existing",
        }
        session.add(PreInvoiceScanResult(scan_id=scan_id, fine_record_id=fine.id,
            investigation_case_id=case.id, triggered_rules=rules,
            rule_results=rule_results, case_action=result["case_action"]))
        session.flush()
        results.append(result)
    return results
