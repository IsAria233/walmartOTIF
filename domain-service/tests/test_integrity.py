from datetime import datetime, timezone
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import create_engine, delete, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db import Base
from app.services import (
    IntegrityViolation,
    add_delivery_allocation,
    add_dispute_line,
)
from app.db.models import (
    Approval,
    ApprovalDecision,
    ASN,
    ASNLine,
    Attachment,
    Delivery,
    DeliveryLine,
    Dispute,
    DisputeLine,
    EvidenceLink,
    EvidenceRecord,
    FineRecord,
    FindingFact,
    InvestigationCase,
    InvestigationFinding,
    LineOutcome,
    POLine,
    PurchaseOrder,
    ReceivingRecord,
    Supplier,
    DistributionCenter,
)


@compiles(JSONB, "sqlite")
def _sqlite_jsonb(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def make_po_line(session, supplier, dc, po_number="PO-1", line_no=1):
    po = PurchaseOrder(
        po_number=po_number,
        supplier=supplier,
        distribution_center=dc,
        freight_terms="prepaid",
        channel="stores",
    )
    line = POLine(purchase_order=po, line_number=line_no)
    session.add(po)
    session.flush()
    return line


def make_fine(session, supplier, dc, po_number="PO-1", line_no=1):
    line = make_po_line(session, supplier, dc, po_number, line_no)
    fine = FineRecord(
        po_line=line,
        po_version_used=1,
        ordered_cases=10,
        received_cases=8,
        non_compliant_cases=2,
        system_accountability="supplier",
        original_amount=Decimal("20.00"),
        case_cost_snapshot=Decimal("10.0000"),
        fine_rate=Decimal("0.030000"),
    )
    session.add(fine)
    session.flush()
    return fine


def make_dc_pair(session):
    supplier = Supplier(supplier_code=f"S-{uuid.uuid4()}", name="Supplier")
    dc = DistributionCenter(dc_code=f"D-{uuid.uuid4()}", name="DC", region="North")
    other_dc = DistributionCenter(dc_code=f"D-{uuid.uuid4()}", name="Other DC")
    session.add_all([supplier, dc, other_dc])
    session.flush()
    return supplier, dc, other_dc


def test_delivery_allocation_within_quantity_is_created(db):
    supplier, dc, _ = make_dc_pair(db)
    line = make_po_line(db, supplier, dc)
    asn = ASN(asn_number="ASN-1")
    asn_line = ASNLine(asn=asn, po_line=line, shipped_cases=10)
    delivery = Delivery(distribution_center=dc)
    db.add_all([asn, delivery])
    db.flush()

    allocation = add_delivery_allocation(
        db, asn_line_id=asn_line.id, delivery_id=delivery.id, allocated_cases=7
    )
    assert allocation.allocated_cases == 7


def test_delivery_allocation_above_quantity_is_rejected(db):
    supplier, dc, _ = make_dc_pair(db)
    line = make_po_line(db, supplier, dc)
    asn = ASN(asn_number="ASN-2")
    asn_line = ASNLine(asn=asn, po_line=line, shipped_cases=10)
    delivery = Delivery(distribution_center=dc)
    db.add_all([asn, delivery])
    db.flush()
    add_delivery_allocation(
        db, asn_line_id=asn_line.id, delivery_id=delivery.id, allocated_cases=7
    )

    with pytest.raises(IntegrityViolation, match="cannot exceed"):
        add_delivery_allocation(
            db, asn_line_id=asn_line.id, delivery_id=delivery.id, allocated_cases=4
        )


def test_delivery_allocation_rejects_a_different_distribution_center(db):
    supplier, dc, other_dc = make_dc_pair(db)
    line = make_po_line(db, supplier, dc)
    asn = ASN(asn_number="ASN-3")
    asn_line = ASNLine(asn=asn, po_line=line, shipped_cases=10)
    delivery = Delivery(distribution_center=other_dc)
    db.add_all([asn, delivery])
    db.flush()

    with pytest.raises(IntegrityViolation, match="distribution center must match"):
        add_delivery_allocation(
            db, asn_line_id=asn_line.id, delivery_id=delivery.id, allocated_cases=3
        )


def test_dispute_line_limit_and_supplier_ownership(db):
    supplier, dc, _ = make_dc_pair(db)
    other_supplier = Supplier(supplier_code=f"S-{uuid.uuid4()}", name="Other")
    db.add(other_supplier)
    db.flush()
    dispute = Dispute(supplier=supplier, submitted_at=datetime.now(timezone.utc))
    db.add(dispute)
    fines = [make_fine(db, supplier, dc, f"PO-{i}") for i in range(3)]
    other_fine = make_fine(db, other_supplier, dc, "PO-OTHER")
    db.flush()

    with pytest.raises(IntegrityViolation, match="supplier must match"):
        add_dispute_line(db, dispute_id=dispute.id, fine_record_id=other_fine.id)
    for fine in fines:
        add_dispute_line(db, dispute_id=dispute.id, fine_record_id=fine.id)
    fourth_fine = make_fine(db, supplier, dc, "PO-FOURTH")
    with pytest.raises(IntegrityViolation, match="at most three"):
        add_dispute_line(db, dispute_id=dispute.id, fine_record_id=fourth_fine.id)


def test_audit_parent_deletions_are_restricted(db):
    supplier, dc, _ = make_dc_pair(db)
    fine = make_fine(db, supplier, dc)
    dispute = Dispute(supplier=supplier, submitted_at=datetime.now(timezone.utc))
    db.add(dispute)
    db.flush()
    case = InvestigationCase(fine_record=fine, origin="pre_invoice_scan", scan_rule="R2")
    finding = InvestigationFinding(investigation_case=case)
    fact = FindingFact(finding=finding, fact_key="receipt", fact_value="8")
    evidence = EvidenceRecord(evidence_type="receipt", snapshot={"cases": 8})
    link = EvidenceLink(finding_fact=fact, evidence_record=evidence, role="supports")
    outcome = LineOutcome(
        finding=finding,
        outcome="partial",
        policy_version="0.1",
        accountable_party="supplier",
        original_amount=Decimal("20.00"),
        corrected_amount=Decimal("10.00"),
    )
    approval = Approval(line_outcome=outcome, approval_type="associate")
    decision = ApprovalDecision(
        approval=approval, auth_user_id=uuid.uuid4(), decision="approved"
    )
    delivery = Delivery(distribution_center=dc)
    asn = ASN(asn_number="ASN-AUDIT")
    asn_line = ASNLine(asn=asn, po_line=fine.po_line, shipped_cases=10)
    delivery_line = DeliveryLine(asn_line=asn_line, delivery=delivery, allocated_cases=10)
    receipt = ReceivingRecord(
        delivery_line=delivery_line,
        received_at=datetime.now(timezone.utc),
        received_cases=8,
    )
    db.add_all([case, finding, fact, evidence, link, outcome, approval, decision, receipt])
    db.commit()

    for model, ident in [
        (InvestigationCase, case.id),
        (InvestigationFinding, finding.id),
        (FindingFact, fact.id),
        (EvidenceRecord, evidence.id),
        (LineOutcome, outcome.id),
        (Approval, approval.id),
        (FineRecord, fine.id),
        (DeliveryLine, delivery_line.id),
    ]:
        with pytest.raises(IntegrityError):
            db.execute(delete(model).where(model.id == ident))
        db.rollback()
        # Restore objects into the next transaction after rollback expiration.
        db.expire_all()
        assert db.get(model, ident) is not None


def test_orm_delete_does_not_null_or_cascade_investigation_history(db):
    supplier, dc, _ = make_dc_pair(db)
    fine = make_fine(db, supplier, dc)
    case = InvestigationCase(fine_record=fine, origin="pre_invoice_scan", scan_rule="R1")
    finding = InvestigationFinding(investigation_case=case)
    db.add(case)
    db.flush()
    case_id, finding_id = case.id, finding.id
    db.commit()

    loaded_case = db.get(InvestigationCase, case_id)
    assert loaded_case.findings[0].id == finding_id
    db.delete(loaded_case)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert db.get(InvestigationCase, case_id) is not None
    assert db.get(InvestigationFinding, finding_id) is not None


def _make_dispute_lines(db):
    supplier, dc, _ = make_dc_pair(db)
    fine_a = make_fine(db, supplier, dc, "PO-CASE-A")
    fine_b = make_fine(db, supplier, dc, "PO-CASE-B")
    dispute_a = Dispute(supplier=supplier, submitted_at=datetime.now(timezone.utc))
    dispute_b = Dispute(supplier=supplier, submitted_at=datetime.now(timezone.utc))
    db.add_all([dispute_a, dispute_b])
    db.flush()
    line_a = DisputeLine(dispute_id=dispute_a.id, fine_record_id=fine_a.id)
    line_b = DisputeLine(dispute_id=dispute_a.id, fine_record_id=fine_b.id)
    line_other_dispute = DisputeLine(dispute_id=dispute_b.id, fine_record_id=fine_a.id)
    db.add_all([line_a, line_b, line_other_dispute])
    db.flush()
    return fine_a, fine_b, dispute_a, dispute_b, line_a, line_b, line_other_dispute


def test_case_composite_foreign_key_rejects_dispute_line_for_another_fine(db):
    fine_a, _, _, _, _, line_b, _ = _make_dispute_lines(db)
    with pytest.raises(IntegrityError):
        db.execute(
            InvestigationCase.__table__.insert().values(
                fine_record_id=fine_a.id,
                dispute_line_id=line_b.id,
                origin="supplier_dispute",
            )
        )


def test_supplier_dispute_requires_dispute_line(db):
    fine_a, _, _, _, *_ = _make_dispute_lines(db)
    with pytest.raises(IntegrityError):
        db.execute(
            InvestigationCase.__table__.insert().values(
                fine_record_id=fine_a.id,
                dispute_line_id=None,
                origin="supplier_dispute",
            )
        )


def test_pre_invoice_scan_rejects_dispute_line(db):
    fine_a, _, _, _, line_a, *_ = _make_dispute_lines(db)
    with pytest.raises(IntegrityError):
        db.execute(
            InvestigationCase.__table__.insert().values(
                fine_record_id=fine_a.id,
                dispute_line_id=line_a.id,
                origin="pre_invoice_scan",
                scan_rule="R1",
            )
        )


def test_attachment_composite_foreign_key_rejects_line_from_another_dispute(db):
    _, _, dispute_a, _, _, _, line_other_dispute = _make_dispute_lines(db)
    with pytest.raises(IntegrityError):
        db.execute(
            Attachment.__table__.insert().values(
                dispute_id=dispute_a.id,
                dispute_line_id=line_other_dispute.id,
                filename="evidence.pdf",
            )
        )


def test_valid_case_and_attachment_ownership_relationships_work(db):
    fine_a, _, dispute_a, _, line_a, *_ = _make_dispute_lines(db)
    case = InvestigationCase(
        fine_record=fine_a,
        dispute_line=line_a,
        origin="supplier_dispute",
    )
    scan_case = InvestigationCase(
        fine_record=fine_a,
        origin="pre_invoice_scan",
        scan_rule="R2",
    )
    attachment = Attachment(dispute=dispute_a, dispute_line=line_a, filename="proof.pdf")
    db.add_all([case, scan_case, attachment])
    db.flush()
    assert case.dispute_line_id == line_a.id
    assert case.fine_record_id == fine_a.id
    assert scan_case.dispute_line_id is None
    assert attachment.dispute_id == dispute_a.id
    assert attachment.dispute_line_id == line_a.id
