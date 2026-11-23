"""Domain Service SQLAlchemy models."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer,
    Numeric, String, Text, UniqueConstraint, Uuid, and_, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship

from ..base import Base
from .common import created_at, uuid_pk

class InvestigationCase(Base):
    __tablename__ = "investigation_cases"
    __table_args__ = (
        CheckConstraint("origin IN ('supplier_dispute', 'pre_invoice_scan')", name="ck_investigation_cases_origin"),
        CheckConstraint("status IN ('pending', 'investigating', 'findings_submitted', 'awaiting_approval', 'handed_off', 'revision_required', 'closed')", name="ck_investigation_cases_status"),
        CheckConstraint("(origin = 'supplier_dispute' AND dispute_line_id IS NOT NULL) OR (origin = 'pre_invoice_scan' AND dispute_line_id IS NULL)", name="ck_investigation_cases_origin_dispute_line"),
        CheckConstraint("scan_rule IS NULL OR (origin = 'pre_invoice_scan' AND scan_rule IN ('R1', 'R2'))", name="ck_investigation_cases_scan_rule"),
        ForeignKeyConstraint(
            ["dispute_line_id", "fine_record_id"],
            ["dispute_lines.id", "dispute_lines.fine_record_id"],
            name="fk_investigation_cases_dispute_line_matches_fine_record",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "fine_record_id", name="uq_investigation_cases_id_fine"),
        Index("ix_investigation_cases_fine_created", "fine_record_id", "created_at"),
        Index("uq_active_case_per_fine", "fine_record_id", unique=True, postgresql_where=text("status <> 'closed'"), sqlite_where=text("status <> 'closed'")),
        Index("ix_investigation_cases_status_created", "status", "created_at", "id"),
        Index("ix_investigation_cases_origin_created", "origin", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    fine_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fine_records.id", ondelete="RESTRICT"), nullable=False)
    dispute_line_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    origin: Mapped[str] = mapped_column(String(50), nullable=False)
    scan_rule: Mapped[str | None] = mapped_column(String(10))
    # Retained as a legacy case-level reference for existing data; new run
    # provenance belongs on individual findings.
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))  # external Agent Service reference
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", server_default="pending")
    created_at: Mapped[datetime] = created_at()
    fine_record: Mapped[FineRecord] = relationship(back_populates="investigation_cases", passive_deletes="all", overlaps="investigation_cases")
    dispute_line: Mapped[DisputeLine | None] = relationship(
        back_populates="investigation_cases",
        primaryjoin="and_(foreign(InvestigationCase.dispute_line_id) == DisputeLine.id, InvestigationCase.fine_record_id == DisputeLine.fine_record_id)",
        foreign_keys=[dispute_line_id],
        passive_deletes="all",
        overlaps="investigation_cases",
    )
    findings: Mapped[list[InvestigationFinding]] = relationship(back_populates="investigation_case", passive_deletes="all")
    dispute_line_cases: Mapped[list[DisputeLineCase]] = relationship(back_populates="investigation_case", passive_deletes="all")
    triggers: Mapped[list[InvestigationCaseTrigger]] = relationship(back_populates="investigation_case", passive_deletes="all")
    evaluations: Mapped[list[Evaluation]] = relationship(back_populates="investigation_case", passive_deletes="all")
    outcomes: Mapped[list[CaseOutcome]] = relationship(back_populates="investigation_case", passive_deletes="all")
    status_events: Mapped[list[CaseStatusEvent]] = relationship(back_populates="investigation_case", order_by="CaseStatusEvent.occurred_at", passive_deletes="all")
    scan_results: Mapped[list[PreInvoiceScanResult]] = relationship(back_populates="investigation_case", passive_deletes="all")


class CaseStatusEvent(Base):
    __tablename__ = "case_status_events"
    __table_args__ = (
        CheckConstraint("to_status IN ('pending', 'investigating', 'findings_submitted', 'awaiting_approval', 'handed_off', 'revision_required', 'closed')", name="ck_case_status_events_to_status"),
        Index("ix_case_status_events_case_time", "investigation_case_id", "occurred_at"),
        UniqueConstraint("investigation_case_id", "agent_run_id", name="uq_case_status_events_agent_run"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    investigation_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_cases.id", ondelete="RESTRICT"), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(50))
    to_status: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))  # external Auth Service UUID
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    handoff_details: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    investigation_case: Mapped[InvestigationCase] = relationship(back_populates="status_events", passive_deletes="all")


class DisputeLineCase(Base):
    __tablename__ = "dispute_line_cases"
    __table_args__ = (
        ForeignKeyConstraint(["dispute_line_id", "fine_record_id"], ["dispute_lines.id", "dispute_lines.fine_record_id"], name="fk_dispute_line_cases_line_fine", ondelete="RESTRICT"),
        ForeignKeyConstraint(["investigation_case_id", "fine_record_id"], ["investigation_cases.id", "investigation_cases.fine_record_id"], name="fk_dispute_line_cases_case_fine", ondelete="RESTRICT"),
        UniqueConstraint("dispute_line_id", name="uq_dispute_line_cases_line"),
        UniqueConstraint("dispute_line_id", "investigation_case_id", name="uq_dispute_line_cases_pair"),
        Index("ix_dispute_line_cases_case", "investigation_case_id"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    dispute_line_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    investigation_case_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    fine_record_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = created_at()
    dispute_line: Mapped[DisputeLine] = relationship(overlaps="dispute_line_cases,investigation_case")
    investigation_case: Mapped[InvestigationCase] = relationship(back_populates="dispute_line_cases", overlaps="dispute_line")


class InvestigationCaseTrigger(Base):
    __tablename__ = "investigation_case_triggers"
    __table_args__ = (
        ForeignKeyConstraint(["investigation_case_id", "fine_record_id"], ["investigation_cases.id", "investigation_cases.fine_record_id"], name="fk_case_triggers_case_fine", ondelete="RESTRICT"),
        CheckConstraint("trigger_rule IN ('R1', 'R2')", name="ck_case_triggers_rule"),
        Index("uq_case_trigger_scan_fine_rule", "scan_id", "fine_record_id", "trigger_rule", unique=True, postgresql_where=text("scan_id <> 'legacy-unknown'"), sqlite_where=text("scan_id <> 'legacy-unknown'")),
        Index("ix_case_triggers_scan", "scan_id"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    investigation_case_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    fine_record_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    trigger_rule: Mapped[str] = mapped_column(String(10), nullable=False)
    scan_id: Mapped[str] = mapped_column(String(150), nullable=False)
    created_at: Mapped[datetime] = created_at()
    investigation_case: Mapped[InvestigationCase] = relationship(back_populates="triggers", passive_deletes="all")


class PreInvoiceScanResult(Base):
    __tablename__ = "pre_invoice_scan_results"
    __table_args__ = (
        CheckConstraint("case_action IN ('created', 'reused_existing', 'skipped')", name="ck_pre_invoice_scan_case_action"),
        UniqueConstraint("scan_id", "fine_record_id", name="uq_pre_invoice_scan_fine"),
        Index("ix_pre_invoice_scan_scan_id", "scan_id"),
        Index("ix_pre_invoice_scan_fine_created", "fine_record_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[str] = mapped_column(String(150), nullable=False)
    fine_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fine_records.id", ondelete="RESTRICT"), nullable=False)
    investigation_case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("investigation_cases.id", ondelete="RESTRICT"))
    triggered_rules: Mapped[list] = mapped_column(JSONB, nullable=False)
    rule_results: Mapped[list] = mapped_column(JSONB, nullable=False)
    case_action: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = created_at()
    investigation_case: Mapped[InvestigationCase | None] = relationship(back_populates="scan_results", passive_deletes="all")


class InvestigationFinding(Base):
    __tablename__ = "investigation_findings"
    __table_args__ = (UniqueConstraint("investigation_case_id", "version_number", name="uq_findings_case_version"), UniqueConstraint("id", "investigation_case_id", name="uq_findings_id_case"), CheckConstraint("version_number > 0", name="ck_findings_version_positive"), Index("ix_investigation_findings_case_created", "investigation_case_id", "created_at"), Index("ix_investigation_findings_agent_run_id", "agent_run_id"))
    id: Mapped[uuid.UUID] = uuid_pk()
    investigation_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_cases.id", name="investigation_findings_investigation_case_id_fkey", ondelete="RESTRICT"), nullable=False)
    cause_code: Mapped[str | None] = mapped_column(String(50))
    summary: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    confidence_level: Mapped[str | None] = mapped_column(String(10))  # high | medium | low
    ruled_out_causes: Mapped[list | None] = mapped_column(JSONB)  # [{"cause": "C1", "reason": "..."}]
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))  # external Agent Service reference
    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))  # set when a reviewer, not the Agent, wrote it
    # Set only with cause OTHER: the party the reviewer named, since the policy has no rule for it.
    reviewer_accountable_party: Mapped[str | None] = mapped_column(String(20))
    handoff_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    handoff_reason: Mapped[str | None] = mapped_column(Text)
    injection_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = created_at()
    investigation_case: Mapped[InvestigationCase] = relationship(back_populates="findings", passive_deletes="all")
    facts: Mapped[list[FindingFact]] = relationship(back_populates="finding", passive_deletes="all")
    line_outcomes: Mapped[list[LineOutcome]] = relationship(back_populates="finding", passive_deletes="all")
    evaluations: Mapped[list[Evaluation]] = relationship(back_populates="finding", passive_deletes="all", overlaps="investigation_case,evaluations")


class Evaluation(Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        ForeignKeyConstraint(["finding_id", "investigation_case_id"], ["investigation_findings.id", "investigation_findings.investigation_case_id"], name="fk_evaluations_finding_same_case", ondelete="RESTRICT"),
        UniqueConstraint("investigation_case_id", "version_number", name="uq_evaluations_case_version"),
        UniqueConstraint("id", "investigation_case_id", name="uq_evaluations_id_case"),
        CheckConstraint("version_number > 0", name="ck_evaluations_version_positive"),
        Index("ix_evaluations_case_created", "investigation_case_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    investigation_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_cases.id", ondelete="RESTRICT"), nullable=False)
    finding_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(ForeignKey("policy_configurations.policy_version", ondelete="RESTRICT"), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    calculation_inputs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    calculation_outputs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = created_at()
    investigation_case: Mapped[InvestigationCase] = relationship(back_populates="evaluations", passive_deletes="all", overlaps="finding,evaluations,outcome")
    finding: Mapped[InvestigationFinding] = relationship(back_populates="evaluations", passive_deletes="all", overlaps="investigation_case,evaluations")
    outcome: Mapped[CaseOutcome | None] = relationship(back_populates="evaluation", uselist=False, passive_deletes="all", overlaps="investigation_case,outcomes")


class CaseOutcome(Base):
    __tablename__ = "case_outcomes"
    __table_args__ = (
        ForeignKeyConstraint(["evaluation_id", "investigation_case_id"], ["evaluations.id", "evaluations.investigation_case_id"], name="fk_case_outcomes_evaluation_same_case", ondelete="RESTRICT"),
        UniqueConstraint("evaluation_id", name="uq_case_outcomes_evaluation"),
        UniqueConstraint("id", "investigation_case_id", name="uq_case_outcomes_id_case"),
        CheckConstraint("status IN ('pending_approval', 'pending_manager_approval', 'approved', 'rejected')", name="ck_case_outcomes_status"),
        Index("ix_case_outcomes_case_created", "investigation_case_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    investigation_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_cases.id", ondelete="RESTRICT"), nullable=False)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending_approval", server_default="pending_approval")
    created_at: Mapped[datetime] = created_at()
    investigation_case: Mapped[InvestigationCase] = relationship(back_populates="outcomes", passive_deletes="all", overlaps="outcome,evaluation")
    evaluation: Mapped[Evaluation] = relationship(back_populates="outcome", passive_deletes="all", overlaps="investigation_case,outcomes")
    line_outcomes: Mapped[list[LineOutcome]] = relationship(back_populates="case_outcome", passive_deletes="all")

class FindingFact(Base):
    __tablename__ = "finding_facts"
    id: Mapped[uuid.UUID] = uuid_pk()
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_findings.id", name="finding_facts_finding_id_fkey", ondelete="RESTRICT"), nullable=False)
    fact_key: Mapped[str] = mapped_column(String(150), nullable=False)
    fact_value: Mapped[str | None] = mapped_column(Text)
    source_description: Mapped[str | None] = mapped_column(Text)
    source_records: Mapped[list | None] = mapped_column(JSONB)  # [{"record_type": "...", "record_id": "<uuid>"}]
    finding: Mapped[InvestigationFinding] = relationship(back_populates="facts", passive_deletes="all")
    evidence_links: Mapped[list[EvidenceLink]] = relationship(back_populates="finding_fact", passive_deletes="all")

class EvidenceRecord(Base):
    __tablename__ = "evidence_records"
    __table_args__ = (Index("ix_evidence_records_kind_created", "evidence_type", "created_at"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    evidence_type: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(200))
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = created_at()
    links: Mapped[list[EvidenceLink]] = relationship(back_populates="evidence_record", passive_deletes="all")

class EvidenceLink(Base):
    __tablename__ = "evidence_links"
    __table_args__ = (UniqueConstraint("finding_fact_id", "evidence_record_id", "role", name="uq_evidence_links_fact_evidence_role"), CheckConstraint("role IN ('supports', 'contradicts', 'context')", name="ck_evidence_links_role"), Index("ix_evidence_links_evidence", "evidence_record_id"))
    id: Mapped[uuid.UUID] = uuid_pk()
    finding_fact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("finding_facts.id", name="evidence_links_finding_fact_id_fkey", ondelete="RESTRICT"), nullable=False)
    evidence_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evidence_records.id", ondelete="RESTRICT"), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    finding_fact: Mapped[FindingFact] = relationship(back_populates="evidence_links", passive_deletes="all")
    evidence_record: Mapped[EvidenceRecord] = relationship(back_populates="links", passive_deletes="all")
