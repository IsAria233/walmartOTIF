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
    from app.db.models import CaseOutcome, Evaluation, PolicyConfiguration
    policy = PolicyConfiguration(
        policy_version="0.1",
        effective_from=datetime(1970, 1, 1, tzinfo=timezone.utc),
        manager_approval_threshold=Decimal("500.00"),
        fine_rate=Decimal("0.030000"),
    )
    evaluation = Evaluation(
        investigation_case=case,
        finding=finding,
        version_number=1,
        policy_version="0.1",
        result={"lines": []},
        calculation_inputs={},
        calculation_outputs={},
    )
    case_outcome = CaseOutcome(
        investigation_case=case,
        evaluation=evaluation,
        status="pending_approval",
    )
    outcome = LineOutcome(
        case_outcome=case_outcome,
        investigation_case_id=case.id,
        evaluated_line_key=str(fine.id),
        finding=finding,
        outcome="partial",
        policy_version="0.1",
        accountable_party="supplier",
        original_amount=Decimal("20.00"),
        corrected_amount=Decimal("10.00"),
        calculated_at=datetime.now(timezone.utc),
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
    db.add_all([case, finding, fact, evidence, link, policy, evaluation, case_outcome, outcome, approval, decision, receipt])
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
        status="closed",
    )
    attachment = Attachment(dispute=dispute_a, dispute_line=line_a, filename="proof.pdf")
    db.add_all([case, scan_case, attachment])
    db.flush()
    assert case.dispute_line_id == line_a.id
    assert case.fine_record_id == fine_a.id
    assert scan_case.dispute_line_id is None
    assert attachment.dispute_id == dispute_a.id
    assert attachment.dispute_line_id == line_a.id


def test_active_case_creation_reuses_and_closed_case_allows_new_history(db):
    from app.services.case_service import get_or_create_active_case

    supplier, dc, _ = make_dc_pair(db)
    fine = make_fine(db, supplier, dc)
    first, created = get_or_create_active_case(db, fine_record_id=fine.id, origin="pre_invoice_scan")
    assert created is True
    again, created = get_or_create_active_case(db, fine_record_id=fine.id, origin="pre_invoice_scan")
    assert created is False
    assert again.id == first.id
    first.status = "closed"
    db.flush()
    historical, created = get_or_create_active_case(db, fine_record_id=fine.id, origin="pre_invoice_scan")
    assert created is True
    assert historical.id != first.id


def test_case_creation_rejects_dispute_line_owned_by_another_supplier(db):
    from app.services.case_service import get_or_create_active_case
    from app.services.exceptions import InvalidRequest

    supplier, dc, _ = make_dc_pair(db)
    other_supplier = Supplier(supplier_code=f"S-{uuid.uuid4()}", name="Other")
    fine = make_fine(db, supplier, dc)
    dispute = Dispute(supplier=other_supplier, submitted_at=datetime.now(timezone.utc))
    db.add_all([other_supplier, dispute])
    db.flush()
    line = DisputeLine(dispute=dispute, fine_record=fine)
    db.add(line)
    db.flush()
    with pytest.raises(InvalidRequest, match="supplier must match"):
        get_or_create_active_case(db, fine_record_id=fine.id, origin="supplier_dispute", dispute_line_ids=[line.id])
    assert db.query(InvestigationCase).filter_by(fine_record_id=fine.id).count() == 0


def test_handed_off_case_can_return_to_investigation(db):
    from app.services.case_service import get_or_create_active_case, transition_case

    supplier, dc, _ = make_dc_pair(db)
    fine = make_fine(db, supplier, dc)
    case, _ = get_or_create_active_case(db, fine_record_id=fine.id, origin="pre_invoice_scan")
    transition_case(db, case_id=case.id, target="investigating")
    transition_case(db, case_id=case.id, target="handed_off", reason="Insufficient evidence")
    transition_case(db, case_id=case.id, target="investigating")
    assert case.status == "investigating"
    assert len(case.status_events) == 4


def test_case_lifecycle_and_versioned_evaluation_outcome_approval(db):
    from app.db.models import CaseOutcome, Evaluation, PolicyConfiguration
    from app.services.case_service import transition_case
    from app.services.evaluation_service import create_evaluation
    from app.services.finding_service import create_finding
    from app.services.outcome_service import create_outcome
    from app.services.approval_service import decide_line
    from app.services.exceptions import Conflict

    supplier, dc, _ = make_dc_pair(db)
    fine = make_fine(db, supplier, dc)
    case = InvestigationCase(fine_record=fine, origin="pre_invoice_scan", status="pending")
    db.add(case)
    db.flush()
    transition_case(db, case_id=case.id, target="investigating")
    with pytest.raises(Conflict):
        transition_case(db, case_id=case.id, target="closed")
    finding = create_finding(db, case_id=case.id, payload={"summary": "records reviewed", "cause_code": "C1"})
    assert finding.version_number == 1
    assert case.status == "findings_submitted"
    db.add(PolicyConfiguration(
        policy_version="0.1",
        effective_from=datetime(1970, 1, 1, tzinfo=timezone.utc),
        manager_approval_threshold=Decimal("500.00"),
        fine_rate=Decimal("0.030000"),
    ))
    db.flush()
    evaluation = create_evaluation(db, case_id=case.id, finding_id=finding.id)
    assert evaluation.version_number == 1
    assert evaluation.result["lines"][0]["corrected_amount"] == "0.60"
    outcome = create_outcome(db, case_id=case.id, evaluation_id=evaluation.id)
    assert outcome.status == "pending_approval"
    line = outcome.line_outcomes[0]
    approval = line.approvals[0]
    with pytest.raises(Conflict):
        transition_case(db, case_id=case.id, target="closed")
    decision = decide_line(db, outcome_id=outcome.id, line_outcome_id=line.id,
        stage="associate", decision="approved", auth_user_id=uuid.uuid4())
    assert decision.decision == "approved"
    assert line.approval_status == "approved"
    assert outcome.status == "approved"
    assert case.status == "closed"
    with pytest.raises(Conflict):
        transition_case(db, case_id=case.id, target="investigating")


def test_rejected_approval_preserves_decision_and_requires_revision(db):
    from app.db.models import PolicyConfiguration
    from app.services.case_service import transition_case
    from app.services.evaluation_service import create_evaluation
    from app.services.finding_service import create_finding
    from app.services.outcome_service import create_outcome
    from app.services.approval_service import decide_line

    supplier, dc, _ = make_dc_pair(db)
    fine = make_fine(db, supplier, dc)
    case = InvestigationCase(fine_record=fine, origin="pre_invoice_scan", status="investigating")
    db.add(case)
    db.add(PolicyConfiguration(policy_version="0.1", effective_from=datetime(1970, 1, 1, tzinfo=timezone.utc), manager_approval_threshold=Decimal("500"), fine_rate=Decimal("0.03")))
    db.flush()
    finding = create_finding(db, case_id=case.id, payload={"summary": "first version", "cause_code": "C1"})
    evaluation = create_evaluation(db, case_id=case.id, finding_id=finding.id)
    outcome = create_outcome(db, case_id=case.id, evaluation_id=evaluation.id)
    line = outcome.line_outcomes[0]
    decide_line(db, outcome_id=outcome.id, line_outcome_id=line.id, stage="associate", decision="rejected", auth_user_id=uuid.uuid4())
    assert line.approval_status == "rejected"
    assert outcome.status == "rejected"
    assert case.status == "revision_required"
    assert len(line.approvals[0].decisions) == 1
    transition_case(db, case_id=case.id, target="investigating")
    second = create_finding(db, case_id=case.id, payload={"summary": "revised version", "cause_code": "C1"})
    assert second.version_number == 2
    assert finding.summary == "first version"
    second_evaluation = create_evaluation(db, case_id=case.id, finding_id=second.id)
    assert second_evaluation.version_number == 2


def test_manager_approval_is_required_above_configured_threshold(db):
    from app.db.models import PolicyConfiguration
    from app.services.case_service import transition_case
    from app.services.evaluation_service import create_evaluation
    from app.services.finding_service import create_finding
    from app.services.outcome_service import create_outcome
    from app.services.approval_service import decide_line
    from app.services.exceptions import Conflict

    supplier, dc, _ = make_dc_pair(db)
    line = make_po_line(db, supplier, dc, "PO-MANAGER")
    fine = FineRecord(po_line=line, po_version_used=1, ordered_cases=10, received_cases=8,
        non_compliant_cases=2, system_accountability="supplier", original_amount=Decimal("1000.00"),
        case_cost_snapshot=Decimal("10.0000"), fine_rate=Decimal("0.030000"))
    case = InvestigationCase(fine_record=fine, origin="pre_invoice_scan", status="investigating")
    db.add_all([fine, case, PolicyConfiguration(policy_version="0.1",
        effective_from=datetime(1970, 1, 1, tzinfo=timezone.utc),
        manager_approval_threshold=Decimal("500.00"), fine_rate=Decimal("0.030000"))])
    db.flush()
    finding = create_finding(db, case_id=case.id, payload={"cause_code": "C1"})
    evaluation = create_evaluation(db, case_id=case.id, finding_id=finding.id)
    outcome = create_outcome(db, case_id=case.id, evaluation_id=evaluation.id)
    line_outcome = outcome.line_outcomes[0]
    user_id = uuid.uuid4()
    with pytest.raises(Conflict):
        decide_line(db, outcome_id=outcome.id, line_outcome_id=line_outcome.id,
            stage="manager", decision="approved", auth_user_id=user_id)
    decide_line(db, outcome_id=outcome.id, line_outcome_id=line_outcome.id,
        stage="associate", decision="approved", auth_user_id=user_id)
    assert line_outcome.approval_status == "pending_manager_approval"
    assert case.status == "awaiting_approval"
    decide_line(db, outcome_id=outcome.id, line_outcome_id=line_outcome.id,
        stage="manager", decision="approved", auth_user_id=user_id)
    assert outcome.status == "approved"
    assert case.status == "closed"


def test_evaluation_fails_explicitly_when_no_policy_configuration_applies(db):
    from app.services.evaluation_service import create_evaluation
    from app.services.finding_service import create_finding
    from app.services.exceptions import PolicyUnavailable

    supplier, dc, _ = make_dc_pair(db)
    fine = make_fine(db, supplier, dc)
    case = InvestigationCase(fine_record=fine, origin="pre_invoice_scan", status="investigating")
    db.add(case)
    db.flush()
    finding = create_finding(db, case_id=case.id, payload={})
    with pytest.raises(PolicyUnavailable, match="No applicable policy"):
        create_evaluation(db, case_id=case.id, finding_id=finding.id)


def test_evaluator_rejects_unsupported_or_conflicting_policy_classification():
    from app.db.models import FineRecord, InvestigationFinding, PolicyConfiguration
    from app.services.exceptions import PolicyUnavailable
    from app.services.policy_evaluator import evaluate_line

    fine = FineRecord(id=uuid.uuid4(), system_accountability="supplier", non_compliant_cases=2,
        case_cost_snapshot=Decimal("10.0000"), original_amount=Decimal("0.60"))
    policy = PolicyConfiguration(policy_version="0.1", fine_rate=Decimal("0.03"))
    with pytest.raises(PolicyUnavailable, match="outside the supported"):
        evaluate_line(fine, InvestigationFinding(cause_code="C6"), policy)
    with pytest.raises(PolicyUnavailable, match="conflicts"):
        evaluate_line(fine, InvestigationFinding(cause_code="C4"), policy)
    finding = InvestigationFinding(cause_code="C3")
    assert evaluate_line(fine, finding, policy)["corrected_amount"] == "0.60"


def test_context_row_serializer_accepts_missing_active_case():
    from app.services.context_service import row

    assert row(None) is None
