"""Thin FastAPI routes for Domain-owned resources and workflows."""
from __future__ import annotations

import math
import os
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import AwareDatetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import (
    ASNPageResponse, ASNResponse, ApprovalDecisionRequest, ApprovalDecisionResponse,
    ApprovalPageResponse, AppointmentPageResponse, CaseCreateRequest,
    CaseQueueResponse, CaseResponse, CaseStatusRequest, DeliveryResponse,
    DisputeCreateRequest, DisputeDetailResponse, DisputePageResponse,
    EvaluationCreateRequest, EvaluationPageResponse, EvaluationResponse,
    FindingCreateRequest, FindingPageResponse, FindingResponse, FinePageResponse,
    FineRecordResponse, GateLogPageResponse, InvestigationContextResponse,
    OutcomeCreateRequest, OutcomeDetailResponse, OutcomePageResponse,
    POLinePageResponse, POLineResponse, POLineVersionPageResponse,
    PurchaseOrderResponse, ReceivingRecordPageResponse, ScanRequest,
    ScanResponse, SupplierResponse, WeatherAlertPageResponse,
)
from app.db.models import (
    Approval, ApprovalDecision, ASN, ASNLine, Attachment, CaseOutcome, Delivery,
    DeliveryLine, Dispute, DisputeLine, DistributionCenter, Evaluation,
    EvidenceLink, EvidenceRecord, FindingFact, FineRecord, GateLog,
    InvestigationCase, InvestigationCaseTrigger, InvestigationFinding,
    LineOutcome, POLine, POLineVersion, PurchaseOrder, ReceivingRecord,
    Supplier, WeatherAlert, AppointmentEvent,
)
from app.db.session import get_db
from app.services import (
    Conflict, IntegrityViolation, InvalidRequest, NotFound, PolicyUnavailable,
    create_evaluation, create_finding, create_outcome, decide_line,
    get_context, get_or_create_active_case, list_cases, run_scan,
    submit_dispute, transition_case,
)
from app.services.exceptions import DomainError

router = APIRouter(prefix="/api/v1")


def serialize(value: Any):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (uuid.UUID, Decimal, datetime)):
        return str(value) if isinstance(value, (uuid.UUID, Decimal)) else value.isoformat()
    if isinstance(value, list):
        return [serialize(item) for item in value]
    if isinstance(value, tuple):
        return [serialize(item) for item in value]
    if hasattr(value, "__table__"):
        return {column.name: serialize(getattr(value, column.name)) for column in value.__table__.columns}
    if isinstance(value, dict):
        return {key: serialize(item) for key, item in value.items()}
    return value


def paginated(session: Session, model, *, page: int, page_size: int, where=()):
    from sqlalchemy import func
    stmt = select(model)
    count = select(func.count(model.id))
    for condition in where:
        stmt, count = stmt.where(condition), count.where(condition)
    total = session.scalar(count) or 0
    items = session.execute(stmt.order_by(model.id).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"items": [serialize(item) for item in items], "page": page, "page_size": page_size,
            "total": total, "total_pages": math.ceil(total / page_size) if total else 0}


def paginated_query(session: Session, stmt, count_stmt, *, page: int, page_size: int, order_by):
    from sqlalchemy import func
    total = session.scalar(count_stmt) or 0
    rows = session.execute(stmt.order_by(*order_by).offset((page - 1) * page_size).limit(page_size)).scalars().unique().all()
    return {"items": [serialize(item) for item in rows], "page": page, "page_size": page_size,
            "total": total, "total_pages": math.ceil(total / page_size) if total else 0}


def finding_response(session: Session, finding: InvestigationFinding) -> dict:
    facts = session.execute(select(FindingFact).where(FindingFact.finding_id == finding.id).order_by(FindingFact.id)).scalars().all()
    result = serialize(finding)
    result["facts"] = []
    for fact in facts:
        links = session.execute(select(EvidenceLink).where(EvidenceLink.finding_fact_id == fact.id)).scalars().all()
        fact_data = serialize(fact)
        fact_data["evidence_ids"] = [link.evidence_record_id for link in links]
        result["facts"].append(fact_data)
    return result


@router.get("/investigation-cases", response_model=CaseQueueResponse)
def case_queue(
    status_filter: str | None = Query(default=None, alias="status", pattern="^(pending|investigating|findings_submitted|awaiting_approval|handed_off|revision_required|closed)$"),
    origin: str | None = Query(default=None, pattern="^(supplier_dispute|pre_invoice_scan)$"),
    source: str | None = Query(default=None, pattern="^(supplier_dispute|pre_invoice_scan)$"),
    fine_record_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None, created_from: AwareDatetime | None = None,
    created_to: AwareDatetime | None = None, page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100), sort_by: str = Query("created_at", pattern="^(created_at|status|origin)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"), db: Session = Depends(get_db),
):
    if origin is not None and source is not None and origin != source:
        raise InvalidRequest("origin and source filters must match when both are supplied")
    if created_from is not None and created_to is not None and created_from > created_to:
        raise InvalidRequest("created_from must not be later than created_to")
    items, total = list_cases(db, status=status_filter, origin=origin or source,
        fine_record_id=fine_record_id, supplier_id=supplier_id,
        created_from=created_from, created_to=created_to, page=page,
        page_size=page_size, sort_by=sort_by, sort_order=sort_order)
    return {"items": items, "page": page, "page_size": page_size,
            "total": total, "total_pages": math.ceil(total / page_size) if total else 0}


@router.post("/investigation-cases", response_model=CaseResponse)
def create_case(payload: CaseCreateRequest, response: Response, db: Session = Depends(get_db)):
    with db.begin():
        case, created = get_or_create_active_case(db, **payload.model_dump())
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return case


@router.get("/investigation-cases/{case_id}", response_model=CaseResponse)
def get_case(case_id: uuid.UUID, db: Session = Depends(get_db)):
    case = db.get(InvestigationCase, case_id)
    if case is None:
        raise NotFound("Investigation Case not found")
    return case


@router.patch("/investigation-cases/{case_id}/status", response_model=CaseResponse)
def patch_case_status(case_id: uuid.UUID, payload: CaseStatusRequest, db: Session = Depends(get_db)):
    with db.begin():
        case = transition_case(db, case_id=case_id, target=payload.status, reason=payload.reason)
    return case


@router.post("/disputes", response_model=DisputeDetailResponse, status_code=201)
def post_dispute(payload: DisputeCreateRequest, db: Session = Depends(get_db)):
    with db.begin():
        dispute = submit_dispute(db, **payload.model_dump())
        result = {"dispute": serialize(dispute), "lines": [serialize(line) for line in dispute.lines],
            "attachments": [serialize(attachment) for attachment in dispute.attachments]}
    return result


@router.get("/disputes/{dispute_id}", response_model=DisputeDetailResponse)
def get_dispute(dispute_id: uuid.UUID, db: Session = Depends(get_db)):
    dispute = db.get(Dispute, dispute_id)
    if dispute is None:
        raise NotFound("Dispute not found")
    return {"dispute": serialize(dispute), "lines": [serialize(line) for line in dispute.lines],
            "attachments": [serialize(item) for item in dispute.attachments]}


@router.post("/investigation-cases/{case_id}/findings", response_model=FindingResponse, status_code=201)
def post_finding(case_id: uuid.UUID, payload: FindingCreateRequest, db: Session = Depends(get_db)):
    with db.begin():
        finding = create_finding(db, case_id=case_id, payload=payload.model_dump())
        result = finding_response(db, finding)
    return result


@router.get("/investigation-cases/{case_id}/findings", response_model=FindingPageResponse)
def list_findings(case_id: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    if db.get(InvestigationCase, case_id) is None:
        raise NotFound("Investigation Case not found")
    condition = InvestigationFinding.investigation_case_id == case_id
    result = paginated_query(db, select(InvestigationFinding).where(condition),
        select(func.count(InvestigationFinding.id)).where(condition), page=page,
        page_size=page_size, order_by=(InvestigationFinding.version_number, InvestigationFinding.id))
    result["items"] = [finding_response(db, row) for row in db.execute(
        select(InvestigationFinding).where(condition).order_by(InvestigationFinding.version_number, InvestigationFinding.id)
        .offset((page - 1) * page_size).limit(page_size)).scalars().all()]
    return result


@router.get("/findings/{finding_id}", response_model=FindingResponse)
def get_finding(finding_id: uuid.UUID, db: Session = Depends(get_db)):
    finding = db.get(InvestigationFinding, finding_id)
    if finding is None:
        raise NotFound("Finding not found")
    return finding_response(db, finding)


@router.post("/investigation-cases/{case_id}/evaluate", response_model=EvaluationResponse, status_code=201)
def post_evaluation(case_id: uuid.UUID, payload: EvaluationCreateRequest, db: Session = Depends(get_db)):
    with db.begin():
        evaluation = create_evaluation(db, case_id=case_id, finding_id=payload.finding_id)
    return evaluation


@router.get("/investigation-cases/{case_id}/evaluations", response_model=EvaluationPageResponse)
def list_evaluations(case_id: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    if db.get(InvestigationCase, case_id) is None:
        raise NotFound("Investigation Case not found")
    condition = Evaluation.investigation_case_id == case_id
    return paginated_query(db, select(Evaluation).where(condition),
        select(func.count(Evaluation.id)).where(condition), page=page,
        page_size=page_size, order_by=(Evaluation.version_number, Evaluation.id))


@router.get("/evaluations/{evaluation_id}", response_model=EvaluationResponse)
def get_evaluation(evaluation_id: uuid.UUID, db: Session = Depends(get_db)):
    item = db.get(Evaluation, evaluation_id)
    if item is None:
        raise NotFound("Evaluation not found")
    return item


@router.post("/investigation-cases/{case_id}/outcome", response_model=OutcomeDetailResponse, status_code=201)
def post_outcome(case_id: uuid.UUID, payload: OutcomeCreateRequest, db: Session = Depends(get_db)):
    with db.begin():
        outcome = create_outcome(db, case_id=case_id, evaluation_id=payload.evaluation_id)
        lines = db.execute(select(LineOutcome).where(LineOutcome.case_outcome_id == outcome.id)).scalars().all()
        result = {"id": outcome.id, "investigation_case_id": outcome.investigation_case_id,
                  "evaluation_id": outcome.evaluation_id, "status": outcome.status,
                  "created_at": outcome.created_at, "line_outcomes": [serialize(line) for line in lines]}
    return serialize(result)


@router.get("/investigation-cases/{case_id}/outcome", response_model=OutcomePageResponse)
def get_outcomes(case_id: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    if db.get(InvestigationCase, case_id) is None:
        raise NotFound("Investigation Case not found")
    condition = CaseOutcome.investigation_case_id == case_id
    page_data = paginated_query(db, select(CaseOutcome).where(condition),
        select(func.count(CaseOutcome.id)).where(condition), page=page,
        page_size=page_size, order_by=(CaseOutcome.created_at.desc(), CaseOutcome.id))
    result = []
    for item in db.execute(select(CaseOutcome).where(condition).order_by(CaseOutcome.created_at.desc(), CaseOutcome.id).offset((page - 1) * page_size).limit(page_size)).scalars():
        lines = db.execute(select(LineOutcome).where(LineOutcome.case_outcome_id == item.id)).scalars().all()
        result.append({"outcome": serialize(item), "line_outcomes": [serialize(line) for line in lines]})
    page_data["items"] = result
    return page_data


ROLES = {"dispute_associate", "compliance_manager", "admin"}
# Who may record a decision at each approval stage (policy section 8).
STAGE_ROLES = {
    "associate": {"dispute_associate", "compliance_manager"},
    "manager": {"compliance_manager"},
}


def _token_claims(request: Request) -> dict:
    """Verify the Auth Service JWT. Both services share JWT_SECRET (HS256)."""
    unauthorized = HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"},
        detail={"error": {"code": "unauthenticated", "message": "A valid bearer token is required"}})
    secret = os.getenv("JWT_SECRET", "")
    if len(secret.encode("utf-8")) < 32:
        raise HTTPException(status_code=503, detail={"error": {"code": "identity_unavailable", "message": "JWT_SECRET is not configured"}})
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise unauthorized
    try:
        return jwt.decode(token.strip(), secret, algorithms=["HS256"], options={"require": ["sub", "role", "exp"]})
    except jwt.InvalidTokenError as exc:
        raise unauthorized from exc


def authenticated_user(request: Request) -> uuid.UUID:
    try:
        return uuid.UUID(str(_token_claims(request)["sub"]))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail={"error": {"code": "unauthenticated", "message": "Token subject is not a user id"}}) from exc


def authenticated_role(request: Request) -> str:
    role = _token_claims(request)["role"]
    if role not in ROLES:
        raise HTTPException(status_code=403, detail={"error": {"code": "forbidden", "message": "Unknown role"}})
    return role


@router.post("/outcomes/{outcome_id}/approvals", response_model=ApprovalDecisionResponse, status_code=201)
def post_approval(outcome_id: uuid.UUID, payload: ApprovalDecisionRequest, request: Request, db: Session = Depends(get_db)):
    user_id = authenticated_user(request)
    role = authenticated_role(request)
    if role not in STAGE_ROLES[payload.stage]:
        raise HTTPException(status_code=403, detail={"error": {"code": "forbidden",
            "message": f"Role {role} cannot record a {payload.stage} approval"}})
    with db.begin():
        decision = decide_line(db, outcome_id=outcome_id,
            line_outcome_id=payload.line_outcome_id, stage=payload.stage,
            decision=payload.decision, auth_user_id=user_id, comment=payload.comment)
    return serialize(decision)


@router.get("/outcomes/{outcome_id}/approvals", response_model=ApprovalPageResponse)
def get_approvals(outcome_id: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    if db.get(CaseOutcome, outcome_id) is None:
        raise NotFound("Outcome not found")
    condition = LineOutcome.case_outcome_id == outcome_id
    page_data = paginated_query(db, select(Approval).join(LineOutcome).where(condition),
        select(func.count(Approval.id)).join(LineOutcome).where(condition), page=page,
        page_size=page_size, order_by=(Approval.created_at, Approval.id))
    page_data["items"] = [{"approval": serialize(item), "decisions": [serialize(d) for d in item.decisions]}
        for item in db.execute(select(Approval).join(LineOutcome).where(condition).order_by(Approval.created_at, Approval.id).offset((page - 1) * page_size).limit(page_size)).scalars().unique()]
    return page_data


@router.post("/pre-invoice-scans/run", response_model=ScanResponse)
def post_scan(payload: ScanRequest, db: Session = Depends(get_db)):
    with db.begin():
        result = run_scan(db, **payload.model_dump())
    return {"scan_id": payload.scan_id, "results": result}


@router.get("/investigation-contexts/{fine_record_id}", response_model=InvestigationContextResponse)
def context(fine_record_id: uuid.UUID, case_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    return get_context(db, fine_record_id, case_id)


@router.get("/fine-records/{fine_record_id}", response_model=FineRecordResponse)
def get_fine(fine_record_id: uuid.UUID, db: Session = Depends(get_db)):
    value = db.get(FineRecord, fine_record_id)
    if value is None:
        raise NotFound("Fine Record not found")
    return serialize(value)


@router.get("/fine-records", response_model=FinePageResponse)
def list_fines(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    return paginated(db, FineRecord, page=page, page_size=page_size)


@router.get("/fine-records/{fine_record_id}/disputes", response_model=DisputePageResponse)
def fine_disputes(fine_record_id: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    if db.get(FineRecord, fine_record_id) is None:
        raise NotFound("Fine Record not found")
    condition = DisputeLine.fine_record_id == fine_record_id
    return paginated_query(db, select(Dispute).join(DisputeLine).where(condition),
        select(func.count(func.distinct(Dispute.id))).join(DisputeLine).where(condition),
        page=page, page_size=page_size, order_by=(Dispute.submitted_at.desc(), Dispute.id))


# Reference-data endpoints share a stable pagination envelope and serialize
# columns only; no ORM instances escape the router.
def read_one(db: Session, model, ident: uuid.UUID):
    item = db.get(model, ident)
    if item is None:
        raise NotFound(f"{model.__name__} not found")
    return serialize(item)


@router.get("/suppliers/{ident}", response_model=SupplierResponse)
def supplier(ident: uuid.UUID, db: Session = Depends(get_db)): return read_one(db, Supplier, ident)
@router.get("/purchase-orders/{ident}", response_model=PurchaseOrderResponse)
def purchase_order(ident: uuid.UUID, db: Session = Depends(get_db)): return read_one(db, PurchaseOrder, ident)
@router.get("/purchase-orders/{ident}/lines", response_model=POLinePageResponse)
def purchase_order_lines(ident: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    if db.get(PurchaseOrder, ident) is None: raise NotFound("Purchase Order not found")
    return paginated(db, POLine, page=page, page_size=page_size, where=(POLine.purchase_order_id == ident,))
@router.get("/po-lines/{ident}/versions", response_model=POLineVersionPageResponse)
def po_line_versions(ident: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    if db.get(POLine, ident) is None: raise NotFound("PO Line not found")
    condition = POLineVersion.po_line_id == ident
    return paginated_query(db, select(POLineVersion).where(condition),
        select(func.count(POLineVersion.id)).where(condition), page=page,
        page_size=page_size, order_by=(POLineVersion.version_number, POLineVersion.id))
@router.get("/asns/{ident}", response_model=ASNResponse)
def asn(ident: uuid.UUID, db: Session = Depends(get_db)): return read_one(db, ASN, ident)
@router.get("/po-lines/{ident}/asns", response_model=ASNPageResponse)
def po_line_asns(ident: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    if db.get(POLine, ident) is None: raise NotFound("PO Line not found")
    condition = ASNLine.po_line_id == ident
    page_data = paginated_query(db, select(ASN).join(ASNLine).where(condition),
        select(func.count(func.distinct(ASN.id))).join(ASNLine).where(condition),
        page=page, page_size=page_size, order_by=(ASN.ship_ts.desc(), ASN.id))
    # shipped_cases lives on the ASN line, so return this PO line's lines with each ASN.
    for item in page_data["items"]:
        lines = db.execute(select(ASNLine).where(ASNLine.asn_id == uuid.UUID(item["id"]), ASNLine.po_line_id == ident)).scalars().all()
        item["lines"] = [serialize(line) for line in lines]
    return page_data
@router.get("/po-lines/{ident}/appointments", response_model=AppointmentPageResponse)
def po_line_appointments(ident: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    if db.get(POLine, ident) is None: raise NotFound("PO Line not found")
    condition = AppointmentEvent.po_line_id == ident
    return paginated_query(db, select(AppointmentEvent).where(condition),
        select(func.count(AppointmentEvent.id)).where(condition), page=page,
        page_size=page_size, order_by=(AppointmentEvent.event_ts, AppointmentEvent.id))
@router.get("/deliveries/{ident}", response_model=DeliveryResponse)
def delivery(ident: uuid.UUID, db: Session = Depends(get_db)): return read_one(db, Delivery, ident)
@router.get("/deliveries/{ident}/gate-logs", response_model=GateLogPageResponse)
def delivery_gate_logs(ident: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    if db.get(Delivery, ident) is None: raise NotFound("Delivery not found")
    condition = GateLog.delivery_id == ident
    return paginated_query(db, select(GateLog).where(condition),
        select(func.count(GateLog.id)).where(condition), page=page,
        page_size=page_size, order_by=(GateLog.check_in_ts, GateLog.id))
@router.get("/po-lines/{ident}/receiving-records", response_model=ReceivingRecordPageResponse)
def po_line_receiving(ident: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    if db.get(POLine, ident) is None: raise NotFound("PO Line not found")
    condition = ASNLine.po_line_id == ident
    stmt = select(ReceivingRecord).join(DeliveryLine).join(ASNLine).where(condition)
    count = select(func.count(ReceivingRecord.id)).join(DeliveryLine).join(ASNLine).where(condition)
    return paginated_query(db, stmt, count, page=page, page_size=page_size,
        order_by=(ReceivingRecord.received_at, ReceivingRecord.id))
@router.get("/distribution-centers/{ident}/weather-alerts", response_model=WeatherAlertPageResponse)
def dc_weather(ident: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    if db.get(DistributionCenter, ident) is None: raise NotFound("Distribution Center not found")
    return paginated(db, WeatherAlert, page=page, page_size=page_size, where=(WeatherAlert.distribution_center_id == ident,))
