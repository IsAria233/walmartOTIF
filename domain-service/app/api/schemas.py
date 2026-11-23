"""Explicit Pydantic contracts for Domain-owned write workflows."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import AwareDatetime, BeforeValidator, BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorResponse(BaseModel):
    error: dict[str, str]


T = TypeVar("T")


def _coerce_sqlite_timezone(value):
    # SQLite drops timezone metadata from timezone=True columns. Normalize only
    # those naive test-adapter values; PostgreSQL aware values pass unchanged.
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


AwareUTCDateTime = Annotated[AwareDatetime, BeforeValidator(_coerce_sqlite_timezone)]


class PageResponse(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int
    total_pages: int


class CaseCreateRequest(BaseModel):
    fine_record_id: UUID
    origin: Literal["supplier_dispute", "pre_invoice_scan"]
    dispute_line_ids: list[UUID] = Field(default_factory=list)


class CaseResponse(ORMModel):
    id: UUID
    fine_record_id: UUID
    origin: str
    status: str
    created_at: AwareUTCDateTime


class CaseStatusRequest(BaseModel):
    status: Literal["pending", "investigating", "findings_submitted", "awaiting_approval", "handed_off", "revision_required", "closed"]
    reason: str | None = None


SourceRecordType = Literal[
    "fine_record", "po_line", "po_line_version", "asn", "asn_line", "appointment_event",
    "delivery", "gate_log", "receiving_record", "weather_alert", "dispute", "attachment",
]


class SourceRecordRef(BaseModel):
    record_type: SourceRecordType
    record_id: UUID


class RuledOutCause(BaseModel):
    cause: Literal["C1", "C2", "C3", "C4", "C5"]
    reason: str = Field(min_length=1)


class FindingFactRequest(BaseModel):
    fact_key: str = Field(min_length=1, max_length=150)
    fact_value: str | None = None
    source_description: str | None = None
    evidence_ids: list[UUID] = Field(default_factory=list)
    source_records: list[SourceRecordRef] = Field(default_factory=list)


class FindingCreateRequest(BaseModel):
    cause_code: str | None = None
    summary: str | None = None
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    confidence_level: Literal["high", "medium", "low"] | None = None
    ruled_out_causes: list[RuledOutCause] = Field(default_factory=list)
    agent_run_id: UUID | None = None
    handoff_required: bool = False
    handoff_reason: str | None = None
    injection_detected: bool = False
    facts: list[FindingFactRequest] = Field(default_factory=list)


class ManualFindingRequest(BaseModel):
    """A reviewer's decision on a handed-off case: the cause and why."""
    model_config = ConfigDict(extra="forbid")

    cause_code: Literal["C1", "C2", "C3", "C4", "C5", "OTHER"]
    rationale: str = Field(min_length=1, max_length=4000)
    # Only with OTHER: the policy assigns the party for C1-C5.
    accountable_party: Literal["supplier", "walmart"] | None = None

    @model_validator(mode="after")
    def party_goes_with_other(self):
        if (self.cause_code == "OTHER") != (self.accountable_party is not None):
            raise ValueError("accountable_party is required for OTHER and not allowed for C1-C5")
        return self

    @field_validator("rationale")
    @classmethod
    def rationale_has_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rationale must not be blank")
        return value.strip()


class FindingFactResponse(BaseModel):
    id: UUID
    fact_key: str
    fact_value: str | None
    source_description: str | None
    evidence_ids: list[UUID] = Field(default_factory=list)
    source_records: list[SourceRecordRef] | None = None


class FindingResponse(BaseModel):
    id: UUID
    investigation_case_id: UUID
    version_number: int
    agent_run_id: UUID | None
    submitted_by_user_id: UUID | None = None
    reviewer_accountable_party: str | None = None
    cause_code: str | None
    summary: str | None
    confidence: Decimal | None
    confidence_level: str | None = None
    ruled_out_causes: list[RuledOutCause] | None = None
    handoff_required: bool
    handoff_reason: str | None
    injection_detected: bool
    created_at: AwareUTCDateTime
    facts: list[FindingFactResponse] = Field(default_factory=list)


class EvaluationCreateRequest(BaseModel):
    finding_id: UUID
    reuse_existing: bool = False


class EvaluationResponse(BaseModel):
    id: UUID
    investigation_case_id: UUID
    finding_id: UUID
    version_number: int
    policy_version: str
    evaluated_at: AwareUTCDateTime
    result: dict[str, Any]
    calculation_inputs: dict[str, Any]
    calculation_outputs: dict[str, Any]


class OutcomeCreateRequest(BaseModel):
    evaluation_id: UUID
    reuse_existing: bool = False


class OutcomeResponse(BaseModel):
    id: UUID
    investigation_case_id: UUID
    evaluation_id: UUID
    status: str
    created_at: AwareUTCDateTime
    line_outcomes: list[dict[str, Any]] = Field(default_factory=list)


class DisputeLineInput(BaseModel):
    fine_record_id: UUID
    amount_disputed: Decimal | None = Field(default=None, ge=0)


class AttachmentInput(BaseModel):
    dispute_line_id: UUID | None = None
    fine_record_id: UUID | None = None
    external_attachment_id: str | None = None
    attachment_type: str | None = None
    filename: str | None = None
    uri: str | None = None
    content_text: str | None = None
    metadata_json: dict[str, Any] | None = None


class DisputeCreateRequest(BaseModel):
    supplier_id: UUID
    external_dispute_id: str | None = Field(default=None, max_length=150)
    reason_category: str | None = Field(default=None, max_length=150)
    reason_text: str | None = None
    amount_disputed: Decimal | None = Field(default=None, ge=0)
    submitted_at: AwareDatetime | None = None
    lines: list[DisputeLineInput] = Field(min_length=1, max_length=3)
    attachments: list[AttachmentInput] = Field(default_factory=list)


class ApprovalDecisionRequest(BaseModel):
    line_outcome_id: UUID
    stage: Literal["associate", "manager"]
    decision: Literal["approved", "rejected"]
    comment: str | None = None


class ScanRequest(BaseModel):
    scan_id: str = Field(min_length=1, max_length=150)
    fine_record_ids: list[UUID] | None = None


class CaseSummary(BaseModel):
    """What a person needs to recognise a case in a list, without opening it."""
    external_fine_id: str | None = None
    metric: str | None = None
    original_amount: Decimal
    po_number: str
    line_number: int
    supplier_name: str


class CaseQueueItem(CaseResponse):
    summary: CaseSummary


class CaseQueueResponse(BaseModel):
    items: list[CaseQueueItem]
    page: int
    page_size: int
    total: int
    total_pages: int


# Stable, explicit DTO declarations mirroring the current public record fields.

class SupplierResponse(ORMModel):
    id: UUID
    supplier_code: str
    name: str
    created_at: AwareUTCDateTime

class DistributionCenterResponse(ORMModel):
    id: UUID
    dc_code: str
    name: str
    timezone: str | None = None
    region: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country_code: str | None = None
    created_at: AwareUTCDateTime

class PurchaseOrderResponse(ORMModel):
    id: UUID
    po_number: str
    supplier_id: UUID
    distribution_center_id: UUID
    status: str | None = None
    freight_terms: str | None = None
    channel: str | None = None
    created_at: AwareUTCDateTime

class POLineResponse(ORMModel):
    id: UUID
    purchase_order_id: UUID
    line_number: int
    item_number: str | None = None
    item_description: str | None = None
    mabd: date | None = None
    standard_transit_days: int | None = None
    case_cost: Decimal | None = None
    created_at: AwareUTCDateTime

class POLineVersionResponse(ORMModel):
    id: UUID
    po_line_id: UUID
    version_number: int
    ordered_cases: int
    issued_at: AwareUTCDateTime
    issued_by: str | None = None
    note: str | None = None

class ASNResponse(ORMModel):
    id: UUID
    asn_number: str
    ship_ts: AwareUTCDateTime | None = None
    created_at: AwareUTCDateTime

class ASNLineResponse(ORMModel):
    id: UUID
    asn_id: UUID
    po_line_id: UUID
    shipped_cases: int


class ASNWithLinesResponse(ASNResponse):
    lines: list[ASNLineResponse] = Field(default_factory=list)

class DeliveryResponse(ORMModel):
    id: UUID
    distribution_center_id: UUID
    delivery_number: str | None = None
    carrier: str | None = None
    trailer_number: str | None = None
    actual_arrival_ts: AwareUTCDateTime | None = None
    created_at: AwareUTCDateTime

class DeliveryLineResponse(ORMModel):
    id: UUID
    asn_line_id: UUID
    delivery_id: UUID
    allocated_cases: int

class AppointmentEventResponse(ORMModel):
    id: UUID
    po_line_id: UUID
    event_ts: AwareUTCDateTime
    action: str
    initiated_by: str | None = None
    appointment_ts: AwareUTCDateTime | None = None
    note: str | None = None

class GateLogResponse(ORMModel):
    id: UUID
    delivery_id: UUID
    check_in_ts: AwareUTCDateTime
    gate_identifier: str | None = None
    note: str | None = None

class ReceivingRecordResponse(ORMModel):
    id: UUID
    delivery_line_id: UUID
    received_at: AwareUTCDateTime
    received_cases: int
    exception_code: str | None = None
    note: str | None = None

class WeatherAlertResponse(ORMModel):
    id: UUID
    distribution_center_id: UUID
    external_alert_id: str | None = None
    alert_date: date
    area: str | None = None
    alert_type: str
    details: dict[str, Any] | None = None

class FineRecordResponse(ORMModel):
    id: UUID
    external_fine_id: str | None = None
    po_line_id: UUID
    po_line_version_id: UUID | None = None
    po_version_used: int
    ordered_cases: int
    received_cases: int
    non_compliant_cases: int
    system_accountability: str
    metric: str | None = None
    original_amount: Decimal
    case_cost_snapshot: Decimal
    fine_rate: Decimal
    recorded_arrival_ts: AwareUTCDateTime | None = None
    status: str | None = None
    created_at: AwareUTCDateTime

class DisputeResponse(ORMModel):
    id: UUID
    supplier_id: UUID
    external_dispute_id: str | None = None
    submitted_at: AwareUTCDateTime
    reason_category: str | None = None
    reason_text: str | None = None
    amount_disputed: Decimal | None = None
    status: str | None = None

class DisputeLineResponse(ORMModel):
    id: UUID
    dispute_id: UUID
    fine_record_id: UUID
    amount_disputed: Decimal | None = None

class AttachmentResponse(ORMModel):
    id: UUID
    dispute_id: UUID
    dispute_line_id: UUID | None = None
    external_attachment_id: str | None = None
    attachment_type: str | None = None
    filename: str | None = None
    uri: str | None = None
    content_text: str | None = None
    metadata_json: dict[str, Any] | None = None
    created_at: AwareUTCDateTime

class HandoffDetails(BaseModel):
    """What the agent leaves for the person who picks up a handed-off case."""
    finding_id: UUID | None = None
    findings: dict[str, Any] | None = None
    tools_called: list[str] = Field(default_factory=list)


class AgentHandoffRequest(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    details: HandoffDetails


class CaseStatusEventResponse(ORMModel):
    id: UUID
    investigation_case_id: UUID
    from_status: str | None = None
    to_status: str
    reason: str | None = None
    actor_user_id: UUID | None = None
    agent_run_id: UUID | None = None
    handoff_details: HandoffDetails | None = None
    occurred_at: AwareUTCDateTime


class CaseDetailResponse(CaseQueueItem):
    handoff: CaseStatusEventResponse | None = None


class EvidenceRecordResponse(ORMModel):
    id: UUID
    evidence_type: str
    external_id: str | None = None
    snapshot: dict[str, Any]
    created_at: AwareUTCDateTime

class EvidenceLinkResponse(ORMModel):
    id: UUID
    finding_fact_id: UUID
    evidence_record_id: UUID
    role: str

class FindingFactRecordResponse(ORMModel):
    id: UUID
    finding_id: UUID
    fact_key: str
    fact_value: str | None = None
    source_description: str | None = None

class LineOutcomeResponse(ORMModel):
    id: UUID
    case_outcome_id: UUID
    investigation_case_id: UUID
    evaluated_line_key: str
    finding_id: UUID
    outcome: str
    policy_version: str
    accountable_party: str
    original_amount: Decimal
    corrected_amount: Decimal
    rationale: str | None = None
    calculated_at: AwareUTCDateTime
    reversal_amount: Decimal
    approval_status: str
    created_at: AwareUTCDateTime

class ApprovalResponse(ORMModel):
    id: UUID
    assigned_to_user_id: UUID | None = None
    line_outcome_id: UUID
    approval_type: str
    status: str
    created_at: AwareUTCDateTime

class ApprovalDecisionRecordResponse(ORMModel):
    id: UUID
    approval_id: UUID
    auth_user_id: UUID
    decision: str
    decided_at: AwareUTCDateTime
    comment: str | None = None

class CaseOutcomeResponse(ORMModel):
    id: UUID
    investigation_case_id: UUID
    evaluation_id: UUID
    status: str
    created_at: AwareUTCDateTime

class EvaluationRecordResponse(ORMModel):
    id: UUID
    investigation_case_id: UUID
    finding_id: UUID
    version_number: int
    policy_version: str
    evaluated_at: AwareUTCDateTime
    result: dict[str, Any]
    calculation_inputs: dict[str, Any]
    calculation_outputs: dict[str, Any]
    created_at: AwareUTCDateTime

class CaseTriggerResponse(ORMModel):
    id: UUID
    investigation_case_id: UUID
    fine_record_id: UUID
    trigger_rule: str
    scan_id: str
    created_at: AwareUTCDateTime

class DisputeDetailResponse(BaseModel):
    dispute: DisputeResponse
    lines: list[DisputeLineResponse]
    attachments: list[AttachmentResponse]


class FindingPageResponse(PageResponse[FindingResponse]):
    pass


class EvaluationPageResponse(PageResponse[EvaluationResponse]):
    pass


class DisputePageResponse(PageResponse[DisputeResponse]):
    pass


class FinePageResponse(PageResponse[FineRecordResponse]):
    pass


class POLinePageResponse(PageResponse[POLineResponse]):
    pass


class POLineVersionPageResponse(PageResponse[POLineVersionResponse]):
    pass


class ASNPageResponse(PageResponse[ASNWithLinesResponse]):
    pass


class AppointmentPageResponse(PageResponse[AppointmentEventResponse]):
    pass


class GateLogPageResponse(PageResponse[GateLogResponse]):
    pass


class ReceivingRecordPageResponse(PageResponse[ReceivingRecordResponse]):
    pass


class WeatherAlertPageResponse(PageResponse[WeatherAlertResponse]):
    pass


class LineOutcomeDetailResponse(BaseModel):
    outcome: CaseOutcomeResponse
    line_outcomes: list[LineOutcomeResponse]


class OutcomePageResponse(PageResponse[LineOutcomeDetailResponse]):
    pass


class ApprovalHistoryResponse(BaseModel):
    approval: ApprovalResponse
    decisions: list[ApprovalDecisionRecordResponse]


class ApprovalPageResponse(PageResponse[ApprovalHistoryResponse]):
    pass


class ScanRuleResultResponse(BaseModel):
    rule: str
    status: str
    reason: str | None = None
    already_recorded: bool | None = None


class ScanFineResultResponse(BaseModel):
    fine_record_id: UUID
    triggered_rules: list[str]
    rule_results: list[ScanRuleResultResponse]
    failed_rules: list[ScanRuleResultResponse]
    case_id: UUID | None
    case_action: Literal["created", "reused_existing", "skipped"]


class ScanResponse(BaseModel):
    scan_id: str
    results: list[ScanFineResultResponse]


class OutcomeDetailResponse(BaseModel):
    id: UUID
    investigation_case_id: UUID
    evaluation_id: UUID
    status: str
    created_at: AwareUTCDateTime
    line_outcomes: list[LineOutcomeResponse]


class ApprovalDecisionResponse(ApprovalDecisionRecordResponse):
    pass


class ASNContextResponse(BaseModel):
    asn: ASNResponse
    lines: list[ASNLineResponse]


class DeliveryContextResponse(BaseModel):
    delivery_line: DeliveryLineResponse
    delivery: DeliveryResponse
    asn_line: ASNLineResponse
    gate_logs: list[GateLogResponse]
    receiving_records: list[ReceivingRecordResponse]


class EvidenceContextResponse(BaseModel):
    fact: FindingFactRecordResponse
    evidence_links: list["EvidenceLinkContextResponse"]


class EvidenceLinkContextResponse(BaseModel):
    link: EvidenceLinkResponse
    evidence: EvidenceRecordResponse | None


class ApprovalContextResponse(BaseModel):
    approval: ApprovalResponse
    decisions: list[ApprovalDecisionRecordResponse]


class LineOutcomeContextResponse(BaseModel):
    line_outcome: LineOutcomeResponse
    approvals: list[ApprovalContextResponse]


class OutcomeContextResponse(BaseModel):
    outcome: CaseOutcomeResponse
    line_outcomes: list[LineOutcomeContextResponse]


class CaseEvidenceContextResponse(BaseModel):
    case: CaseResponse
    dispute_lines: list[DisputeLineResponse]
    triggers: list[CaseTriggerResponse]
    latest_finding: FindingResponse | None
    finding_history: list[FindingResponse]
    latest_evaluation: EvaluationResponse | None
    evaluation_history: list[EvaluationResponse]
    evidence_context: list[EvidenceContextResponse]
    outcomes: list[OutcomeContextResponse]


class DisputeContextResponse(BaseModel):
    dispute: DisputeResponse
    lines: list[DisputeLineResponse]
    attachments: list[AttachmentResponse]


class InvestigationContextResponse(BaseModel):
    fine_record: FineRecordResponse
    purchase_order: PurchaseOrderResponse
    supplier: SupplierResponse
    distribution_center: DistributionCenterResponse
    po_line: POLineResponse
    po_line_versions: list[POLineVersionResponse]
    asns: list[ASNContextResponse]
    appointments: list[AppointmentEventResponse]
    deliveries: list[DeliveryContextResponse]
    weather_alerts: list[WeatherAlertResponse]
    disputes: list[DisputeContextResponse]
    attachments: list[AttachmentResponse]
    active_case: CaseResponse | None
    case_history: list[CaseResponse]
    case_context: list[CaseEvidenceContextResponse]


EvidenceContextResponse.model_rebuild()
InvestigationContextResponse.model_rebuild()
