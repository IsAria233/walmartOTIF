"""Read-only aggregation of Domain records for one Fine Record."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ASN, ASNLine, AppointmentEvent, Attachment, CaseOutcome, Delivery,
    DeliveryLine, Dispute, DisputeLine, Evaluation, EvidenceLink,
    DisputeLineCase, DistributionCenter, EvidenceRecord, FineRecord, FindingFact, GateLog, InvestigationCase,
    InvestigationCaseTrigger, InvestigationFinding, LineOutcome, POLine,
    POLineVersion, PurchaseOrder, ReceivingRecord, Supplier, WeatherAlert,
)
from app.services.exceptions import InvalidRequest, NotFound


def row(model) -> dict | None:
    if model is None:
        return None
    result = {}
    for column in model.__table__.columns:
        value = getattr(model, column.name)
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        elif value is not None and value.__class__.__name__ == "UUID":
            value = str(value)
        elif value is not None and value.__class__.__name__ == "Decimal":
            value = str(value)
        result[column.name] = value
    return result


def get_context(session: Session, fine_record_id: UUID, case_id: UUID | None = None) -> dict:
    fine = session.get(FineRecord, fine_record_id)
    if fine is None:
        raise NotFound("Fine Record not found")
    line = session.get(POLine, fine.po_line_id)
    po = session.get(PurchaseOrder, line.purchase_order_id)
    supplier = session.get(Supplier, po.supplier_id)
    dc = session.get(DistributionCenter, po.distribution_center_id)
    cases = session.execute(select(InvestigationCase).where(InvestigationCase.fine_record_id == fine_record_id).order_by(InvestigationCase.created_at, InvestigationCase.id)).scalars().all()
    if case_id is not None and not any(case.id == case_id for case in cases):
        raise InvalidRequest("Case does not belong to the requested Fine Record")
    selected = [c for c in cases if c.id == case_id] if case_id else cases
    case_items = []
    for case in selected:
        findings = session.execute(select(InvestigationFinding).where(InvestigationFinding.investigation_case_id == case.id).order_by(InvestigationFinding.version_number.desc())).scalars().all()
        evaluations = session.execute(select(Evaluation).where(Evaluation.investigation_case_id == case.id).order_by(Evaluation.version_number.desc())).scalars().all()
        facts_and_evidence = []
        if findings:
            facts = session.execute(select(FindingFact).where(FindingFact.finding_id == findings[0].id)).scalars().all()
            for fact in facts:
                links = session.execute(select(EvidenceLink).where(EvidenceLink.finding_fact_id == fact.id)).scalars().all()
                facts_and_evidence.append({"fact": row(fact), "evidence_links": [
                    {"link": row(link), "evidence": row(session.get(EvidenceRecord, link.evidence_record_id))}
                    for link in links
                ]})
        outcomes = session.execute(select(CaseOutcome).where(CaseOutcome.investigation_case_id == case.id).order_by(CaseOutcome.created_at.desc())).scalars().all()
        outcome_context = []
        for outcome in outcomes:
            outcome_lines = session.execute(select(LineOutcome).where(LineOutcome.case_outcome_id == outcome.id)).scalars().all()
            outcome_context.append({"outcome": row(outcome), "line_outcomes": [
                {"line_outcome": row(item), "approvals": [
                    {"approval": row(approval), "decisions": [row(decision) for decision in approval.decisions]}
                    for approval in item.approvals
                ]} for item in outcome_lines
            ]})
        triggers = session.execute(select(InvestigationCaseTrigger).where(InvestigationCaseTrigger.investigation_case_id == case.id)).scalars().all()
        associations = session.execute(select(DisputeLine).join(DisputeLineCase, DisputeLineCase.dispute_line_id == DisputeLine.id).where(DisputeLineCase.investigation_case_id == case.id)).scalars().all()
        case_items.append({
            "case": row(case),
            "dispute_lines": [row(item) for item in associations],
            "triggers": [row(item) for item in triggers],
            "latest_finding": row(findings[0]) if findings else None,
            "finding_history": [row(f) for f in findings],
            "latest_evaluation": row(evaluations[0]) if evaluations else None,
            "evaluation_history": [row(e) for e in evaluations],
            "evidence_context": facts_and_evidence,
            "outcomes": outcome_context,
        })
    disputes = session.execute(select(Dispute).join(DisputeLine).where(DisputeLine.fine_record_id == fine_record_id)).scalars().unique().all()
    dispute_context = []
    dispute_ids = [item.id for item in disputes]
    for dispute in disputes:
        dispute_lines = session.execute(select(DisputeLine).where(DisputeLine.dispute_id == dispute.id)).scalars().all()
        dispute_attachments = session.execute(select(Attachment).where(Attachment.dispute_id == dispute.id)).scalars().all()
        dispute_context.append({"dispute": row(dispute), "lines": [row(item) for item in dispute_lines],
                                "attachments": [row(item) for item in dispute_attachments]})
    versions = session.execute(select(POLineVersion).where(POLineVersion.po_line_id == line.id).order_by(POLineVersion.version_number.desc())).scalars().all()
    asns = session.execute(select(ASN).join(ASNLine).where(ASNLine.po_line_id == line.id)).scalars().unique().all()
    asn_context = [{"asn": row(asn), "lines": [row(item) for item in session.execute(
        select(ASNLine).where(ASNLine.asn_id == asn.id, ASNLine.po_line_id == line.id)
    ).scalars()]} for asn in asns]
    delivery_lines = session.execute(select(DeliveryLine).join(ASNLine).where(ASNLine.po_line_id == line.id)).scalars().all()
    deliveries = []
    for dl in delivery_lines:
        delivery = session.get(Delivery, dl.delivery_id)
        deliveries.append({"delivery_line": row(dl), "delivery": row(delivery),
            "asn_line": row(session.get(ASNLine, dl.asn_line_id)),
            "gate_logs": [row(x) for x in session.execute(select(GateLog).where(GateLog.delivery_id == dl.delivery_id)).scalars()],
            "receiving_records": [row(x) for x in session.execute(select(ReceivingRecord).where(ReceivingRecord.delivery_line_id == dl.id)).scalars()]})
    attachments = session.execute(select(Attachment).where(Attachment.dispute_id.in_(dispute_ids))).scalars().all() if dispute_ids else []
    delivery_dates = {
        datetime.fromisoformat(item["delivery"]["actual_arrival_ts"]).date()
        for item in deliveries if item["delivery"] and item["delivery"]["actual_arrival_ts"] is not None
    }
    if not delivery_dates and fine.recorded_arrival_ts is not None:
        delivery_dates.add(fine.recorded_arrival_ts.date())
    relevant_weather_dates = {day for arrival_day in delivery_dates for day in (arrival_day, arrival_day.fromordinal(arrival_day.toordinal() - 1))}
    weather_stmt = select(WeatherAlert).where(WeatherAlert.distribution_center_id == po.distribution_center_id)
    if relevant_weather_dates:
        weather_stmt = weather_stmt.where(WeatherAlert.alert_date.in_(relevant_weather_dates))
    weather = session.execute(weather_stmt.order_by(WeatherAlert.alert_date.desc())).scalars().all()
    # This aggregation intentionally performs no writes or rule evaluation.
    return {
        "fine_record": row(fine),
        "purchase_order": row(po),
        "supplier": row(supplier),
        "distribution_center": row(dc),
        "po_line": row(line),
        "po_line_versions": [row(v) for v in versions],
        "asns": asn_context,
        "appointments": [row(item) for item in session.execute(select(AppointmentEvent).where(AppointmentEvent.po_line_id == line.id).order_by(AppointmentEvent.event_ts)).scalars()],
        "deliveries": deliveries,
        "weather_alerts": [row(item) for item in weather],
        "disputes": dispute_context,
        "attachments": [row(item) for item in attachments],
        "active_case": row(next((item for item in cases if item.status != "closed"), None)),
        "case_history": [row(item) for item in cases],
        "case_context": case_items,
    }
