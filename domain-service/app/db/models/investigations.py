"""Domain Service SQLAlchemy models."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer,
    Numeric, String, Text, UniqueConstraint, Uuid, and_, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship

from ..base import Base
from .common import created_at, uuid_pk

class InvestigationCase(Base):
    __tablename__ = "investigation_cases"
    __table_args__ = (
        CheckConstraint("origin IN ('supplier_dispute', 'pre_invoice_scan')", name="ck_investigation_cases_origin"),
        CheckConstraint("(origin = 'supplier_dispute' AND dispute_line_id IS NOT NULL) OR (origin = 'pre_invoice_scan' AND dispute_line_id IS NULL)", name="ck_investigation_cases_origin_dispute_line"),
        CheckConstraint("scan_rule IS NULL OR (origin = 'pre_invoice_scan' AND scan_rule IN ('R1', 'R2'))", name="ck_investigation_cases_scan_rule"),
        ForeignKeyConstraint(
            ["dispute_line_id", "fine_record_id"],
            ["dispute_lines.id", "dispute_lines.fine_record_id"],
            name="fk_investigation_cases_dispute_line_matches_fine_record",
            ondelete="RESTRICT",
        ),
        Index("ix_investigation_cases_fine_created", "fine_record_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    fine_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fine_records.id", ondelete="RESTRICT"), nullable=False)
    dispute_line_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    origin: Mapped[str] = mapped_column(String(50), nullable=False)
    scan_rule: Mapped[str | None] = mapped_column(String(10))
    # Retained as a legacy case-level reference for existing data; new run
    # provenance belongs on individual findings.
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))  # external Agent Service reference
    status: Mapped[str | None] = mapped_column(String(50))
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

class InvestigationFinding(Base):
    __tablename__ = "investigation_findings"
    __table_args__ = (Index("ix_investigation_findings_case_created", "investigation_case_id", "created_at"), Index("ix_investigation_findings_agent_run_id", "agent_run_id"))
    id: Mapped[uuid.UUID] = uuid_pk()
    investigation_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_cases.id", name="investigation_findings_investigation_case_id_fkey", ondelete="RESTRICT"), nullable=False)
    cause_code: Mapped[str | None] = mapped_column(String(50))
    summary: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))  # external Agent Service reference
    handoff_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    handoff_reason: Mapped[str | None] = mapped_column(Text)
    injection_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = created_at()
    investigation_case: Mapped[InvestigationCase] = relationship(back_populates="findings", passive_deletes="all")
    facts: Mapped[list[FindingFact]] = relationship(back_populates="finding", passive_deletes="all")
    line_outcome: Mapped[LineOutcome | None] = relationship(back_populates="finding", uselist=False, passive_deletes="all")

class FindingFact(Base):
    __tablename__ = "finding_facts"
    id: Mapped[uuid.UUID] = uuid_pk()
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_findings.id", name="finding_facts_finding_id_fkey", ondelete="RESTRICT"), nullable=False)
    fact_key: Mapped[str] = mapped_column(String(150), nullable=False)
    fact_value: Mapped[str | None] = mapped_column(Text)
    source_description: Mapped[str | None] = mapped_column(Text)
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
