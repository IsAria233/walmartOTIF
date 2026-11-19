"""Transactional Dispute submission; transaction is owned by the API caller."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Attachment, Dispute, FineRecord, POLine, PurchaseOrder
from app.services.case_service import get_or_create_active_case
from app.services.dispute_service import add_dispute_line
from app.services.exceptions import InvalidRequest, NotFound


def submit_dispute(
    session: Session, *, supplier_id: uuid.UUID, lines: list[dict],
    attachments: list[dict] | None = None, reason_text: str | None = None,
) -> Dispute:
    if not 1 <= len(lines) <= 3:
        raise InvalidRequest("A Dispute must contain between one and three Fine Records")
    fine_ids = [line["fine_record_id"] for line in lines]
    if len(set(fine_ids)) != len(fine_ids):
        raise InvalidRequest("A Fine Record may appear only once in a Dispute")
    # Pre-lock all line Fine Records in stable order to avoid deadlocks when
    # concurrent submissions overlap but arrive in different payload orders.
    locked_ids = session.execute(
        select(FineRecord.id).where(FineRecord.id.in_(fine_ids)).order_by(FineRecord.id).with_for_update()
    ).scalars().all()
    if set(locked_ids) != set(fine_ids):
        raise NotFound("Fine Record not found")
    dispute = Dispute(
        supplier_id=supplier_id, submitted_at=datetime.now(timezone.utc), status="submitted", reason_text=reason_text,
    )
    session.add(dispute)
    session.flush()
    seen = set()
    line_ids_by_fine: dict[uuid.UUID, list[uuid.UUID]] = {}
    for line_data in lines:
        fine_id = line_data["fine_record_id"]
        if fine_id in seen:
            raise InvalidRequest("A Fine Record may appear only once in a Dispute")
        seen.add(fine_id)
        fine = session.get(FineRecord, fine_id)
        if fine is None:
            raise NotFound("Fine Record not found")
        po = session.get(POLine, fine.po_line_id)
        order = session.get(PurchaseOrder, po.purchase_order_id)
        if order.supplier_id != supplier_id:
            raise InvalidRequest("Fine Record supplier must match Dispute supplier")
        line = add_dispute_line(
            session,
            dispute_id=dispute.id,
            fine_record_id=fine_id,
            amount_disputed=line_data.get("amount_disputed"),
        )
        line_ids_by_fine.setdefault(fine_id, []).append(line.id)
        get_or_create_active_case(
            session,
            fine_record_id=fine_id,
            origin="supplier_dispute",
            dispute_line_ids=[line.id],
        )
    for item in attachments or []:
        line_id = item.get("dispute_line_id")
        if item.get("fine_record_id") is not None:
            linked = line_ids_by_fine.get(item["fine_record_id"], [])
            if len(linked) != 1:
                raise InvalidRequest("Attachment Fine Record must identify exactly one submitted Dispute Line")
            if line_id is not None and line_id != linked[0]:
                raise InvalidRequest("Attachment Dispute Line and Fine Record references do not match")
            line_id = linked[0]
        if line_id is not None and not any(line_id in ids for ids in line_ids_by_fine.values()):
            raise InvalidRequest("Attachment Dispute Line must be included in this submission")
        session.add(Attachment(
            dispute_id=dispute.id,
            dispute_line_id=line_id,
            external_attachment_id=item.get("external_attachment_id"),
            attachment_type=item.get("attachment_type"),
            filename=item.get("filename"),
            uri=item.get("uri"),
            metadata_json=item.get("metadata_json"),
        ))
    session.flush()
    return dispute
