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

class FineRecord(Base):
    __tablename__ = "fine_records"
    __table_args__ = (CheckConstraint("ordered_cases >= 0", name="ck_fine_records_ordered_nonnegative"), CheckConstraint("received_cases >= 0", name="ck_fine_records_received_nonnegative"), CheckConstraint("non_compliant_cases >= 0", name="ck_fine_records_noncompliant_nonnegative"), CheckConstraint("original_amount >= 0", name="ck_fine_records_amount_nonnegative"), CheckConstraint("case_cost_snapshot >= 0", name="ck_fine_records_case_cost_nonnegative"), CheckConstraint("fine_rate >= 0", name="ck_fine_records_rate_nonnegative"), ForeignKeyConstraint(["po_line_version_id", "po_line_id"], ["po_line_versions.id", "po_line_versions.po_line_id"], name="fk_fine_records_version_matches_line", ondelete="RESTRICT", use_alter=False), Index("ix_fine_records_po_line_created", "po_line_id", "created_at"))
    id: Mapped[uuid.UUID] = uuid_pk()
    external_fine_id: Mapped[str | None] = mapped_column(String(150), unique=True)
    po_line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("po_lines.id", name="fine_records_po_line_id_fkey", ondelete="RESTRICT"), nullable=False)
    po_line_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    po_version_used: Mapped[int] = mapped_column(Integer, nullable=False)
    ordered_cases: Mapped[int] = mapped_column(Integer, nullable=False)
    received_cases: Mapped[int] = mapped_column(Integer, nullable=False)
    non_compliant_cases: Mapped[int] = mapped_column(Integer, nullable=False)
    system_accountability: Mapped[str] = mapped_column(String(50), nullable=False)
    metric: Mapped[str | None] = mapped_column(String(50))
    original_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    case_cost_snapshot: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    fine_rate: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    recorded_arrival_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = created_at()
    po_line: Mapped[POLine] = relationship(back_populates="fine_records", passive_deletes="all")
    po_line_version: Mapped[POLineVersion | None] = relationship(foreign_keys=[po_line_version_id])
    disputes: Mapped[list[DisputeLine]] = relationship(back_populates="fine_record", passive_deletes="all")
    investigation_cases: Mapped[list[InvestigationCase]] = relationship(back_populates="fine_record", passive_deletes="all")

class Dispute(Base):
    __tablename__ = "disputes"
    __table_args__ = (Index("ix_disputes_submitted_at", "submitted_at"), Index("ix_disputes_supplier_submitted", "supplier_id", "submitted_at"))
    id: Mapped[uuid.UUID] = uuid_pk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False)
    external_dispute_id: Mapped[str | None] = mapped_column(String(150), unique=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason_category: Mapped[str | None] = mapped_column(String(150))
    reason_text: Mapped[str | None] = mapped_column(Text)
    amount_disputed: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    status: Mapped[str | None] = mapped_column(String(50))
    supplier: Mapped[Supplier] = relationship(back_populates="disputes")
    lines: Mapped[list[DisputeLine]] = relationship(back_populates="dispute", passive_deletes="all")
    attachments: Mapped[list[Attachment]] = relationship(back_populates="dispute", passive_deletes="all", overlaps="dispute_line,attachments")

class DisputeLine(Base):
    __tablename__ = "dispute_lines"
    __table_args__ = (
        UniqueConstraint("dispute_id", "fine_record_id", name="uq_dispute_lines_fine"),
        UniqueConstraint("id", "fine_record_id", name="uq_dispute_lines_id_fine_record"),
        UniqueConstraint("id", "dispute_id", name="uq_dispute_lines_id_dispute"),
        Index("ix_dispute_lines_fine", "fine_record_id"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    dispute_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("disputes.id", name="dispute_lines_dispute_id_fkey", ondelete="RESTRICT"), nullable=False)
    fine_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fine_records.id", ondelete="RESTRICT"), nullable=False)
    amount_disputed: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    dispute: Mapped[Dispute] = relationship(back_populates="lines", passive_deletes="all")
    fine_record: Mapped[FineRecord] = relationship(back_populates="disputes", passive_deletes="all")
    investigation_cases: Mapped[list[InvestigationCase]] = relationship(back_populates="dispute_line", passive_deletes="all", overlaps="fine_record,investigation_cases")
    attachments: Mapped[list[Attachment]] = relationship(back_populates="dispute_line", passive_deletes="all", overlaps="dispute,attachments")

class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dispute_line_id", "dispute_id"],
            ["dispute_lines.id", "dispute_lines.dispute_id"],
            name="fk_attachments_dispute_line_matches_dispute",
            ondelete="RESTRICT",
        ),
        Index("ix_attachments_dispute_line_id", "dispute_line_id"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    dispute_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("disputes.id", name="attachments_dispute_id_fkey", ondelete="RESTRICT"), nullable=False)
    dispute_line_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    external_attachment_id: Mapped[str | None] = mapped_column(String(150))
    attachment_type: Mapped[str | None] = mapped_column(String(100))
    filename: Mapped[str | None] = mapped_column(String(500))
    uri: Mapped[str | None] = mapped_column(Text)
    # Attachments are text documents (BOL, POD, appointment email, PO copy).
    content_text: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()
    dispute: Mapped[Dispute] = relationship(back_populates="attachments", passive_deletes="all", overlaps="attachments")
    dispute_line: Mapped[DisputeLine | None] = relationship(
        back_populates="attachments",
        primaryjoin="and_(foreign(Attachment.dispute_line_id) == DisputeLine.id, Attachment.dispute_id == DisputeLine.dispute_id)",
        foreign_keys=[dispute_line_id],
    )
