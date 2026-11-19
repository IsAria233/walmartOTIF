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

class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[uuid.UUID] = uuid_pk()
    supplier_code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = created_at()
    purchase_orders: Mapped[list[PurchaseOrder]] = relationship(back_populates="supplier", passive_deletes="all")
    disputes: Mapped[list[Dispute]] = relationship(back_populates="supplier", passive_deletes="all")

class DistributionCenter(Base):
    __tablename__ = "distribution_centers"
    id: Mapped[uuid.UUID] = uuid_pk()
    dc_code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str | None] = mapped_column(String(64))
    region: Mapped[str | None] = mapped_column(String(150))
    address_line1: Mapped[str | None] = mapped_column(String(255))
    address_line2: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(150))
    state: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(30))
    country_code: Mapped[str | None] = mapped_column(String(2))
    created_at: Mapped[datetime] = created_at()
    purchase_orders: Mapped[list[PurchaseOrder]] = relationship(back_populates="distribution_center", passive_deletes="all")
    weather_alerts: Mapped[list[WeatherAlert]] = relationship(back_populates="distribution_center", passive_deletes="all")
    deliveries: Mapped[list[Delivery]] = relationship(back_populates="distribution_center", passive_deletes="all")

class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (Index("ix_purchase_orders_supplier_dc", "supplier_id", "distribution_center_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    # External Walmart PO identifiers are treated as globally unique because the current design does not establish supplier-scoped numbering.
    po_number: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False)
    distribution_center_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("distribution_centers.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str | None] = mapped_column(String(50))
    freight_terms: Mapped[str | None] = mapped_column(String(50))
    channel: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = created_at()
    supplier: Mapped[Supplier] = relationship(back_populates="purchase_orders", passive_deletes="all")
    distribution_center: Mapped[DistributionCenter] = relationship(back_populates="purchase_orders", passive_deletes="all")
    lines: Mapped[list[POLine]] = relationship(back_populates="purchase_order", passive_deletes="all")

class POLine(Base):
    __tablename__ = "po_lines"
    __table_args__ = (UniqueConstraint("purchase_order_id", "line_number", name="uq_po_lines_order_line"), CheckConstraint("line_number > 0", name="ck_po_lines_line_positive"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_orders.id", name="po_lines_purchase_order_id_fkey", ondelete="RESTRICT"), nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    item_number: Mapped[str | None] = mapped_column(String(100))
    item_description: Mapped[str | None] = mapped_column(String(500))
    mabd: Mapped[date | None] = mapped_column(Date)
    standard_transit_days: Mapped[int | None] = mapped_column(Integer)
    case_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    created_at: Mapped[datetime] = created_at()
    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines", passive_deletes="all")
    versions: Mapped[list[POLineVersion]] = relationship(back_populates="po_line", order_by="POLineVersion.version_number", passive_deletes="all")
    asn_lines: Mapped[list[ASNLine]] = relationship(back_populates="po_line", passive_deletes="all")
    appointment_events: Mapped[list[AppointmentEvent]] = relationship(back_populates="po_line", passive_deletes="all")
    fine_records: Mapped[list[FineRecord]] = relationship(back_populates="po_line", passive_deletes="all")

class POLineVersion(Base):
    __tablename__ = "po_line_versions"
    __table_args__ = (UniqueConstraint("po_line_id", "version_number", name="uq_po_line_versions_number"), UniqueConstraint("id", "po_line_id", name="uq_po_line_versions_id_po_line"), CheckConstraint("version_number > 0", name="ck_po_line_versions_positive"), CheckConstraint("ordered_cases >= 0", name="ck_po_line_versions_ordered_nonnegative"), Index("ix_po_line_versions_effective", "po_line_id", "issued_at"))
    id: Mapped[uuid.UUID] = uuid_pk()
    po_line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("po_lines.id", name="po_line_versions_po_line_id_fkey", ondelete="RESTRICT"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    ordered_cases: Mapped[int] = mapped_column(Integer, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    issued_by: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
    po_line: Mapped[POLine] = relationship(back_populates="versions", passive_deletes="all")

class ASN(Base):
    __tablename__ = "asns"
    __table_args__ = (Index("ix_asns_ship_ts", "ship_ts"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    asn_number: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    ship_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    lines: Mapped[list[ASNLine]] = relationship(back_populates="asn", passive_deletes="all")

class ASNLine(Base):
    __tablename__ = "asn_lines"
    __table_args__ = (CheckConstraint("shipped_cases >= 0", name="ck_asn_lines_shipped_nonnegative"), Index("ix_asn_lines_po_line", "po_line_id"))
    id: Mapped[uuid.UUID] = uuid_pk()
    asn_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asns.id", name="asn_lines_asn_id_fkey", ondelete="RESTRICT"), nullable=False)
    po_line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("po_lines.id", name="asn_lines_po_line_id_fkey", ondelete="RESTRICT"), nullable=False)
    shipped_cases: Mapped[int] = mapped_column(Integer, nullable=False)
    asn: Mapped[ASN] = relationship(back_populates="lines", passive_deletes="all")
    po_line: Mapped[POLine] = relationship(back_populates="asn_lines", passive_deletes="all")
    delivery_lines: Mapped[list[DeliveryLine]] = relationship(back_populates="asn_line", passive_deletes="all")

class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (Index("ix_deliveries_arrival", "actual_arrival_ts"), Index("ix_deliveries_dc_arrival", "distribution_center_id", "actual_arrival_ts"))
    id: Mapped[uuid.UUID] = uuid_pk()
    distribution_center_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("distribution_centers.id", name="deliveries_distribution_center_id_fkey", ondelete="RESTRICT"), nullable=False)
    delivery_number: Mapped[str | None] = mapped_column(String(100), unique=True)
    carrier: Mapped[str | None] = mapped_column(String(255))
    trailer_number: Mapped[str | None] = mapped_column(String(100))
    actual_arrival_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    distribution_center: Mapped[DistributionCenter] = relationship(back_populates="deliveries")
    lines: Mapped[list[DeliveryLine]] = relationship(back_populates="delivery", passive_deletes="all")
    gate_logs: Mapped[list[GateLog]] = relationship(back_populates="delivery", passive_deletes="all")

class DeliveryLine(Base):
    __tablename__ = "delivery_lines"
    __table_args__ = (CheckConstraint("allocated_cases > 0", name="ck_delivery_lines_allocated_positive"), UniqueConstraint("asn_line_id", "delivery_id", name="uq_delivery_lines_asn_delivery"), Index("ix_delivery_lines_delivery", "delivery_id"))
    id: Mapped[uuid.UUID] = uuid_pk()
    asn_line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asn_lines.id", ondelete="RESTRICT"), nullable=False)
    delivery_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deliveries.id", name="delivery_lines_delivery_id_fkey", ondelete="RESTRICT"), nullable=False)
    allocated_cases: Mapped[int] = mapped_column(Integer, nullable=False)
    asn_line: Mapped[ASNLine] = relationship(back_populates="delivery_lines", passive_deletes="all")
    delivery: Mapped[Delivery] = relationship(back_populates="lines", passive_deletes="all")
    receiving_records: Mapped[list[ReceivingRecord]] = relationship(back_populates="delivery_line", passive_deletes="all")

class AppointmentEvent(Base):
    __tablename__ = "appointment_events"
    __table_args__ = (Index("ix_appointment_events_po_line_ts", "po_line_id", "event_ts"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    po_line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("po_lines.id", name="appointment_events_po_line_id_fkey", ondelete="RESTRICT"), nullable=False)
    event_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    initiated_by: Mapped[str | None] = mapped_column(String(50))
    appointment_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    po_line: Mapped[POLine] = relationship(back_populates="appointment_events", passive_deletes="all")

class GateLog(Base):
    __tablename__ = "gate_logs"
    __table_args__ = (Index("ix_gate_logs_delivery_checkin", "delivery_id", "check_in_ts"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    delivery_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deliveries.id", name="gate_logs_delivery_id_fkey", ondelete="RESTRICT"), nullable=False)
    check_in_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gate_identifier: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)
    delivery: Mapped[Delivery] = relationship(back_populates="gate_logs", passive_deletes="all")

class ReceivingRecord(Base):
    __tablename__ = "receiving_records"
    __table_args__ = (CheckConstraint("received_cases >= 0", name="ck_receiving_records_cases_nonnegative"), Index("ix_receiving_records_delivery_line_received", "delivery_line_id", "received_at"))
    id: Mapped[uuid.UUID] = uuid_pk()
    delivery_line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("delivery_lines.id", name="receiving_records_delivery_line_id_fkey", ondelete="RESTRICT"), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_cases: Mapped[int] = mapped_column(Integer, nullable=False)
    exception_code: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)
    delivery_line: Mapped[DeliveryLine] = relationship(back_populates="receiving_records", passive_deletes="all")

class WeatherAlert(Base):
    __tablename__ = "weather_alerts"
    __table_args__ = (Index("ix_weather_alerts_dc_date", "distribution_center_id", "alert_date"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    distribution_center_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("distribution_centers.id", name="weather_alerts_distribution_center_id_fkey", ondelete="RESTRICT"), nullable=False)
    external_alert_id: Mapped[str | None] = mapped_column(String(150))
    alert_date: Mapped[date] = mapped_column(Date, nullable=False)
    area: Mapped[str | None] = mapped_column(String(255))
    alert_type: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB)
    distribution_center: Mapped[DistributionCenter] = relationship(back_populates="weather_alerts", passive_deletes="all")
