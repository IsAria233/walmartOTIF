"""Dispute integrity helpers for Domain Service."""
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Dispute, DisputeLine, FineRecord, POLine, PurchaseOrder
from app.services.exceptions import IntegrityViolation


def add_dispute_line(
    session: Session,
    *,
    dispute_id: uuid.UUID,
    fine_record_id: uuid.UUID,
    amount_disputed=None,
) -> DisputeLine:
    """Add a supplier-matching fine line, enforcing the POC limit of three."""
    dispute = session.execute(
        select(Dispute).where(Dispute.id == dispute_id).with_for_update()
    ).scalar_one()
    fine_and_order = session.execute(
        select(FineRecord, PurchaseOrder)
        .join(POLine, FineRecord.po_line_id == POLine.id)
        .join(PurchaseOrder, POLine.purchase_order_id == PurchaseOrder.id)
        .where(FineRecord.id == fine_record_id)
        .with_for_update()
    ).one()
    _, purchase_order = fine_and_order
    if dispute.supplier_id != purchase_order.supplier_id:
        raise IntegrityViolation("fine record supplier must match dispute supplier")
    count = session.scalar(
        select(func.count(DisputeLine.id)).where(DisputeLine.dispute_id == dispute_id)
    )
    if count >= 3:
        raise IntegrityViolation("a dispute can contain at most three fine lines")
    line = DisputeLine(
        dispute_id=dispute.id,
        fine_record_id=fine_record_id,
        amount_disputed=amount_disputed,
    )
    session.add(line)
    session.flush()
    return line
