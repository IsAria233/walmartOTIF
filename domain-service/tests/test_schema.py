from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import configure_mappers

from app.db import Base
from app.db.models import (
    Approval, ApprovalDecision, ASN, ASNLine, Delivery, DeliveryLine,
    Dispute, DisputeLine, EvidenceLink, EvidenceRecord, FindingFact,
    FineRecord, InvestigationCase, InvestigationFinding, LineOutcome,
    POLine, POLineVersion, ReceivingRecord,
)


def test_schema_has_all_domain_tables_and_configures_relationships():
    configure_mappers()
    assert len(Base.metadata.tables) == 25
    assert "agent_runs" not in Base.metadata.tables
    assert "users" not in Base.metadata.tables


def test_key_relationships_and_constraint_choices():
    assert POLine.versions.property.mapper.class_ is POLineVersion
    assert ASN.lines.property.mapper.class_ is ASNLine
    assert Delivery.lines.property.mapper.class_ is DeliveryLine
    assert DeliveryLine.receiving_records.property.mapper.class_ is ReceivingRecord
    assert InvestigationCase.findings.property.mapper.class_ is InvestigationFinding
    assert InvestigationFinding.line_outcome.property.mapper.class_ is LineOutcome
    assert LineOutcome.approvals.property.mapper.class_ is Approval
    assert Approval.decisions.property.mapper.class_ is ApprovalDecision

    delivery_constraints = {c.name: c for c in DeliveryLine.__table__.constraints}
    assert "ck_delivery_lines_allocated_positive" in delivery_constraints
    assert not any(isinstance(c, CheckConstraint) and "SUM" in str(c.sqltext).upper() for c in delivery_constraints.values())
    assert any(isinstance(c, UniqueConstraint) and tuple(col.name for col in c.columns) == ("dispute_id", "fine_record_id") for c in DisputeLine.__table__.constraints)
    assert not any(isinstance(c, CheckConstraint) and "COUNT" in str(c.sqltext).upper() for c in Dispute.__table__.constraints)
    assert any(isinstance(c, ForeignKeyConstraint) and "delivery_lines.id" in str(c) for c in ReceivingRecord.__table__.constraints)


def test_snapshot_and_money_types_are_postgresql_appropriate():
    assert FineRecord.__table__.c.original_amount.type.__class__.__name__ == "Numeric"
    assert EvidenceRecord.__table__.c.snapshot.type.__class__.__name__ == "JSONB"
    assert FindingFact.__table__.c.finding_id.foreign_keys
    assert EvidenceLink.__table__.c.evidence_record_id.foreign_keys


def test_review_fields_and_restrictive_audit_relationships():
    from app.db.models import (
        Attachment, DistributionCenter, Dispute, PurchaseOrder,
    )

    assert "distribution_center_id" in Delivery.__table__.c
    assert "supplier_id" in Dispute.__table__.c
    assert "dispute_line_id" in Attachment.__table__.c
    assert {"freight_terms", "channel"}.issubset(PurchaseOrder.__table__.c.keys())
    assert {"region", "address_line1", "city", "state", "postal_code"}.issubset(
        DistributionCenter.__table__.c.keys()
    )
    assert {
        "agent_run_id", "handoff_required", "handoff_reason", "injection_detected"
    }.issubset(InvestigationFinding.__table__.c.keys())
    assert "scan_rule" in InvestigationCase.__table__.c
    assert "assigned_to_user_id" in Approval.__table__.c
    assert {
        "policy_version", "accountable_party", "original_amount", "calculated_at"
    }.issubset(LineOutcome.__table__.c.keys())

    for table in Base.metadata.tables.values():
        for constraint in table.foreign_key_constraints:
            assert constraint.ondelete == "RESTRICT", (table.name, constraint.name)
    for mapper in Base.registry.mappers:
        for relationship in mapper.relationships:
            assert "delete" not in relationship.cascade, (
                mapper.class_.__name__, relationship.key
            )


def test_case_and_attachment_composite_ownership_constraints():
    from app.db.models import Attachment, InvestigationCase

    case_fk = next(
        c for c in InvestigationCase.__table__.constraints
        if isinstance(c, ForeignKeyConstraint)
        and c.name == "fk_investigation_cases_dispute_line_matches_fine_record"
    )
    assert [element.target_fullname for element in case_fk.elements] == [
        "dispute_lines.id", "dispute_lines.fine_record_id"
    ]
    attachment_fk = next(
        c for c in Attachment.__table__.constraints
        if isinstance(c, ForeignKeyConstraint)
        and c.name == "fk_attachments_dispute_line_matches_dispute"
    )
    assert [element.target_fullname for element in attachment_fk.elements] == [
        "dispute_lines.id", "dispute_lines.dispute_id"
    ]
