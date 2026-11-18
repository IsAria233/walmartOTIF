"""Allocation integrity helpers for Domain Service.

Call these inside the caller's SQLAlchemy transaction. PostgreSQL row locks
serialize competing writes for the same ASN line or dispute under the default
READ COMMITTED isolation level.
"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ASNLine, Delivery, DeliveryLine, PurchaseOrder
from app.services.exceptions import IntegrityViolation

def validate_delivery_distribution_center(
    session: Session, *, asn_line_id: uuid.UUID, delivery_id: uuid.UUID
) -> None:
    """Require the ASN line's PO destination to match the physical delivery."""
    asn_line = session.execute(
        select(ASNLine).where(ASNLine.id == asn_line_id).with_for_update()
    ).scalar_one()
    delivery = session.execute(
        select(Delivery).where(Delivery.id == delivery_id).with_for_update()
    ).scalar_one()
    purchase_order = session.execute(
        select(PurchaseOrder)
        .where(PurchaseOrder.id == asn_line.po_line.purchase_order_id)
        .with_for_update()
    ).scalar_one()
    order_dc_id = purchase_order.distribution_center_id
    if delivery.distribution_center_id != order_dc_id:
        raise IntegrityViolation(
            "delivery distribution center must match the ASN line purchase order destination"
        )


def add_delivery_allocation(
    session: Session,
    *,
    asn_line_id: uuid.UUID,
    delivery_id: uuid.UUID,
    allocated_cases: int,
) -> DeliveryLine:
    """Create an allocation within the ASN quantity and at the correct DC."""
    if allocated_cases <= 0:
        raise IntegrityViolation("allocated_cases must be greater than zero")
    validate_delivery_distribution_center(
        session, asn_line_id=asn_line_id, delivery_id=delivery_id
    )
    asn_line = session.get(ASNLine, asn_line_id)
    already_allocated = session.scalar(
        select(func.coalesce(func.sum(DeliveryLine.allocated_cases), 0)).where(
            DeliveryLine.asn_line_id == asn_line_id
        )
    )
    if already_allocated + allocated_cases > asn_line.shipped_cases:
        raise IntegrityViolation("delivery allocations cannot exceed ASN shipped_cases")
    allocation = DeliveryLine(
        asn_line_id=asn_line_id,
        delivery_id=delivery_id,
        allocated_cases=allocated_cases,
    )
    session.add(allocation)
    session.flush()
    return allocation
