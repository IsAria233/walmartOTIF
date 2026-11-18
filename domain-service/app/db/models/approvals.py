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

class LineOutcome(Base):
    __tablename__ = "line_outcomes"
    __table_args__ = (UniqueConstraint("finding_id", name="uq_line_outcomes_finding"), CheckConstraint("outcome IN ('uphold', 'waive', 'partial')", name="ck_line_outcomes_outcome"), CheckConstraint("accountable_party IN ('supplier', 'walmart')", name="ck_line_outcomes_accountable_party"), CheckConstraint("corrected_amount >= 0", name="ck_line_outcomes_amount_nonnegative"), CheckConstraint("original_amount >= 0", name="ck_line_outcomes_original_amount_nonnegative"))
    id: Mapped[uuid.UUID] = uuid_pk()
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_findings.id", name="line_outcomes_finding_id_fkey", ondelete="RESTRICT"), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    accountable_party: Mapped[str] = mapped_column(String(30), nullable=False)
    original_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    corrected_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = created_at()
    finding: Mapped[InvestigationFinding] = relationship(back_populates="line_outcome", passive_deletes="all")
    approvals: Mapped[list[Approval]] = relationship(back_populates="line_outcome", passive_deletes="all")

class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (Index("ix_approvals_outcome_status", "line_outcome_id", "status"), Index("ix_approvals_assigned_user", "assigned_to_user_id"))
    id: Mapped[uuid.UUID] = uuid_pk()
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))  # external Auth Service reference
    line_outcome_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("line_outcomes.id", name="approvals_line_outcome_id_fkey", ondelete="RESTRICT"), nullable=False)
    approval_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="pending")
    created_at: Mapped[datetime] = created_at()
    line_outcome: Mapped[LineOutcome] = relationship(back_populates="approvals", passive_deletes="all")
    decisions: Mapped[list[ApprovalDecision]] = relationship(back_populates="approval", order_by="ApprovalDecision.decided_at", passive_deletes="all")

class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"
    __table_args__ = (CheckConstraint("decision IN ('approved', 'rejected')", name="ck_approval_decisions_decision"), Index("ix_approval_decisions_approval_time", "approval_id", "decided_at"))
    id: Mapped[uuid.UUID] = uuid_pk()
    approval_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approvals.id", name="approval_decisions_approval_id_fkey", ondelete="RESTRICT"), nullable=False)
    auth_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)  # external Auth Service reference
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    comment: Mapped[str | None] = mapped_column(Text)
    approval: Mapped[Approval] = relationship(back_populates="decisions", passive_deletes="all")
