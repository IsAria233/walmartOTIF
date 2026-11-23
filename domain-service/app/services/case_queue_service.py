"""Filtered, stably ordered Investigation Case queue."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import FineRecord, InvestigationCase, POLine, PurchaseOrder


def list_cases(session: Session, *, status: str | None = None, origin: str | None = None, fine_record_id: UUID | None = None, supplier_id: UUID | None = None, created_from: datetime | None = None, created_to: datetime | None = None, page: int = 1, page_size: int = 20, sort_by: str = "created_at", sort_order: str = "desc"):
    allowed = {"created_at": InvestigationCase.created_at, "status": InvestigationCase.status, "origin": InvestigationCase.origin}
    sort_col = allowed.get(sort_by, InvestigationCase.created_at)
    stmt = select(InvestigationCase)
    count_stmt = select(func.count(InvestigationCase.id))
    if supplier_id is not None:
        joins = (FineRecord, POLine, PurchaseOrder)
        stmt = stmt.join(FineRecord, FineRecord.id == InvestigationCase.fine_record_id).join(POLine, POLine.id == FineRecord.po_line_id).join(PurchaseOrder, PurchaseOrder.id == POLine.purchase_order_id)
        count_stmt = count_stmt.join(FineRecord, FineRecord.id == InvestigationCase.fine_record_id).join(POLine, POLine.id == FineRecord.po_line_id).join(PurchaseOrder, PurchaseOrder.id == POLine.purchase_order_id)
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
        count_stmt = count_stmt.where(PurchaseOrder.supplier_id == supplier_id)
    for column, value in ((InvestigationCase.status, status), (InvestigationCase.origin, origin), (InvestigationCase.fine_record_id, fine_record_id)):
        if value is not None:
            stmt = stmt.where(column == value)
            count_stmt = count_stmt.where(column == value)
    if created_from is not None:
        stmt, count_stmt = stmt.where(InvestigationCase.created_at >= created_from), count_stmt.where(InvestigationCase.created_at >= created_from)
    if created_to is not None:
        stmt, count_stmt = stmt.where(InvestigationCase.created_at <= created_to), count_stmt.where(InvestigationCase.created_at <= created_to)
    total = session.scalar(count_stmt) or 0
    ordering = sort_col.asc() if sort_order == "asc" else sort_col.desc()
    # Load what case_summary reads in the same query, not one query per row.
    stmt = stmt.options(
        joinedload(InvestigationCase.fine_record).joinedload(FineRecord.po_line)
        .joinedload(POLine.purchase_order).joinedload(PurchaseOrder.supplier)
    )
    items = session.execute(stmt.order_by(ordering, InvestigationCase.id.asc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return items, total


def case_summary(case: InvestigationCase) -> dict:
    """Readable identifiers for one case: the fine, its PO line and the supplier."""
    fine = case.fine_record
    line = fine.po_line
    order = line.purchase_order
    return {
        "external_fine_id": fine.external_fine_id, "metric": fine.metric, "original_amount": fine.original_amount,
        "po_number": order.po_number, "line_number": line.line_number, "supplier_name": order.supplier.name,
    }
