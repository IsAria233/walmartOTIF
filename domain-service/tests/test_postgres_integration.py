"""Real-PostgreSQL SCRUM-15 integrity/concurrency tests.

Run only with SCRUM15_TEST_DATABASE_URL targeting the disposable
walmart_otif_scrum15_test database. The fixture refuses any other target.
"""
from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    ASN, ASNLine, Approval, ApprovalDecision, AppointmentEvent, CaseOutcome, CaseStatusEvent,
    Delivery, Dispute, DisputeLine, DisputeLineCase, DistributionCenter,
    Evaluation, FineRecord, InvestigationCase, InvestigationCaseTrigger,
    InvestigationFinding, LineOutcome, POLine, PolicyConfiguration,
    PreInvoiceScanResult, PurchaseOrder, Supplier,
)
from app.services.approval_service import decide_line
from app.services.case_service import get_or_create_active_case, record_agent_handoff, transition_case
from app.services.dispute_submission_service import submit_dispute
from app.services.evaluation_service import create_evaluation
from app.services.exceptions import Conflict, InvalidRequest
from app.services.finding_service import create_finding
from app.services.outcome_service import create_outcome
from app.services.scan_service import run_scan


DATABASE_NAME = "walmart_otif_scrum15_test"


@pytest.fixture(scope="session")
def pg_engine():
    value = os.getenv("SCRUM15_TEST_DATABASE_URL")
    if not value:
        pytest.skip("SCRUM15_TEST_DATABASE_URL is not configured")
    url = make_url(value)
    if url.database != DATABASE_NAME:
        pytest.fail(f"Refusing database tests against unexpected database {url.database!r}")
    if url.username != "stephenhuang":
        pytest.fail(f"Refusing database tests under unexpected role {url.username!r}")
    engine = create_engine(url, pool_size=12, max_overflow=8, pool_pre_ping=True)
    with engine.connect() as connection:
        database, role, revision = connection.execute(text(
            "SELECT current_database(), current_user, (SELECT version_num FROM alembic_version)"
        )).one()
        assert database == DATABASE_NAME and role == "stephenhuang"
        assert revision == "0006_agent_handoff"
    yield engine
    engine.dispose()


def _fine(session: Session, *, supplier: Supplier | None = None,
          original: Decimal = Decimal("20.00"), non_compliant: int = 2,
          case_cost: Decimal = Decimal("10.0000")) -> FineRecord:
    supplier = supplier or Supplier(supplier_code=f"pg-{uuid.uuid4()}", name="Postgres Supplier")
    dc = DistributionCenter(dc_code=f"pg-{uuid.uuid4()}", name="Postgres DC")
    po = PurchaseOrder(po_number=f"PG-{uuid.uuid4()}", supplier=supplier, distribution_center=dc)
    line = POLine(purchase_order=po, line_number=1)
    ordered = max(10, non_compliant)
    fine = FineRecord(
        po_line=line, po_version_used=1, ordered_cases=ordered,
        received_cases=ordered - non_compliant, non_compliant_cases=non_compliant,
        system_accountability="supplier", original_amount=original,
        case_cost_snapshot=case_cost, fine_rate=Decimal("0.030000"),
    )
    session.add_all([supplier, dc, po, line, fine])
    session.flush()
    return fine


def _seed_fine(engine, **kwargs) -> uuid.UUID:
    with Session(engine) as session, session.begin():
        fine = _fine(session, **kwargs)
        fine_id = fine.id
    return fine_id


def _concurrent(engine, fn, count=2):
    barrier = threading.Barrier(count)

    def work():
        barrier.wait(timeout=10)
        try:
            with Session(engine) as session, session.begin():
                value = fn(session)
                return ("ok", value)
        except (Conflict, InvalidRequest) as exc:
            return ("domain_error", type(exc).__name__)
        except IntegrityError:
            return ("integrity_error", None)

    with ThreadPoolExecutor(max_workers=count) as pool:
        return [future.result(timeout=30) for future in [pool.submit(work) for _ in range(count)]]


def _seed_approval_workflow(engine, *, original=Decimal("20.00"),
                            non_compliant=2, case_cost=Decimal("10.0000")):
    with Session(engine) as session, session.begin():
        fine = _fine(session, original=original, non_compliant=non_compliant, case_cost=case_cost)
        case = InvestigationCase(fine_record=fine, origin="pre_invoice_scan", status="investigating")
        session.add(case)
        session.flush()
        finding = create_finding(session, case_id=case.id, payload={"cause_code": "C1", "summary": "PG test"})
        evaluation = create_evaluation(session, case_id=case.id, finding_id=finding.id)
        outcome = create_outcome(session, case_id=case.id, evaluation_id=evaluation.id)
        ids = case.id, outcome.id, outcome.line_outcomes[0].id
    return ids


def test_postgres_migration_schema_constraints_and_audit_triggers(pg_engine):
    with pg_engine.connect() as connection:
        tables = set(connection.scalars(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'"
        )))
        assert len(tables) == 32
        assert "investigation_case_triggers" in tables and "case_outcomes" in tables
        indexes = dict(connection.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public' "
            "AND indexname IN ('uq_active_case_per_fine','uq_case_trigger_scan_fine_rule')"
        )).all())
        assert "WHERE" in indexes["uq_active_case_per_fine"] and "status" in indexes["uq_active_case_per_fine"]
        assert "WHERE" in indexes["uq_case_trigger_scan_fine_rule"]
        composite_fks = set(connection.scalars(text(
            "SELECT conname FROM pg_constraint WHERE contype='f' AND conname IN "
            "('fk_dispute_line_cases_line_fine','fk_dispute_line_cases_case_fine',"
            "'fk_evaluations_finding_same_case','fk_case_outcomes_evaluation_same_case',"
            "'fk_line_outcomes_case_outcome_same_case')"
        )))
        assert len(composite_fks) == 5
        trigger_tables = set(connection.scalars(text(
            "SELECT DISTINCT event_object_table FROM information_schema.triggers "
            "WHERE trigger_schema='public'"
        )))
        assert {"investigation_findings", "evaluations", "approval_decisions", "case_outcomes", "line_outcomes"} <= trigger_tables

    case_id, outcome_id, line_id = _seed_approval_workflow(pg_engine)
    with Session(pg_engine) as session:
        finding_id = session.scalar(select(InvestigationFinding.id).where(InvestigationFinding.investigation_case_id == case_id))
        evaluation_id = session.scalar(select(Evaluation.id).where(Evaluation.investigation_case_id == case_id))
        decision = decide_line(session, outcome_id=outcome_id, line_outcome_id=line_id,
            stage="associate", decision="approved", auth_user_id=uuid.uuid4())
        session.commit()
        decision_id = decision.id

    prohibited = [
        ("UPDATE investigation_findings SET summary='changed' WHERE id=:id", {"id": finding_id}),
        ("DELETE FROM investigation_findings WHERE id=:id", {"id": finding_id}),
        ("UPDATE evaluations SET result='{}'::jsonb WHERE id=:id", {"id": evaluation_id}),
        ("DELETE FROM evaluations WHERE id=:id", {"id": evaluation_id}),
        ("UPDATE approval_decisions SET comment='changed' WHERE id=:id", {"id": decision_id}),
        ("DELETE FROM approval_decisions WHERE id=:id", {"id": decision_id}),
        ("DELETE FROM case_outcomes WHERE id=:id", {"id": outcome_id}),
        ("UPDATE line_outcomes SET corrected_amount=99 WHERE id=:id", {"id": line_id}),
        ("DELETE FROM line_outcomes WHERE id=:id", {"id": line_id}),
    ]
    for statement, params in prohibited:
        with Session(pg_engine) as session:
            with pytest.raises(DBAPIError):
                with session.begin():
                    session.execute(text(statement), params)


def test_postgres_active_case_creation_is_serialized_and_reused(pg_engine):
    fine_id = _seed_fine(pg_engine)

    def create(session):
        case, created = get_or_create_active_case(session, fine_record_id=fine_id, origin="pre_invoice_scan")
        return str(case.id), created

    results = _concurrent(pg_engine, create)
    assert [tag for tag, _ in results] == ["ok", "ok"]
    assert len({value[0] for _, value in results}) == 1
    assert sorted(value[1] for _, value in results) == [False, True]

    reused = _concurrent(pg_engine, create, count=4)
    assert all(tag == "ok" and value[0] == results[0][1][0] and value[1] is False for tag, value in reused)


def test_postgres_concurrent_agent_handoff_records_one_event(pg_engine):
    fine_id = _seed_fine(pg_engine)
    run_id = uuid.uuid4()
    with Session(pg_engine) as session, session.begin():
        case, _ = get_or_create_active_case(session, fine_record_id=fine_id, origin="pre_invoice_scan")
        case_id = case.id

    def handoff(session):
        event = record_agent_handoff(
            session, case_id=case_id, run_id=run_id, reason="Missing ASN",
            details={"evidence_counts": {"asn": 0}, "missing_sources": ["asn"], "finding_id": None},
        )
        return event.id

    results = _concurrent(pg_engine, handoff)
    assert [tag for tag, _ in results] == ["ok", "ok"]
    assert results[0][1] == results[1][1]
    with Session(pg_engine) as session:
        assert session.get(InvestigationCase, case_id).status == "handed_off"
        events = session.scalars(select(CaseStatusEvent).where(
            CaseStatusEvent.investigation_case_id == case_id,
            CaseStatusEvent.to_status == "handed_off",
        )).all()
        assert len(events) == 1
        assert events[0].from_status == "pending"
        assert events[0].handoff_details["missing_sources"] == ["asn"]


def test_postgres_concurrent_finding_version_allocation_is_serialized(pg_engine):
    fine_id = _seed_fine(pg_engine)
    with Session(pg_engine) as session, session.begin():
        case = InvestigationCase(fine_record_id=fine_id, origin="pre_invoice_scan", status="investigating")
        session.add(case)
        session.flush()
        case_id = case.id

    def submit(session):
        finding = create_finding(session, case_id=case_id, payload={"cause_code": "C1"})
        return finding.version_number

    results = _concurrent(pg_engine, submit)
    assert sorted(tag for tag, _ in results) == ["domain_error", "ok"]
    with Session(pg_engine) as session:
        versions = session.scalars(select(InvestigationFinding.version_number).where(
            InvestigationFinding.investigation_case_id == case_id
        )).all()
        assert versions == [1]


def test_postgres_concurrent_evaluation_version_allocation(pg_engine):
    fine_id = _seed_fine(pg_engine)
    with Session(pg_engine) as session, session.begin():
        case = InvestigationCase(fine_record_id=fine_id, origin="pre_invoice_scan", status="findings_submitted")
        session.add(case)
        session.flush()
        findings = [InvestigationFinding(investigation_case_id=case.id, version_number=i, cause_code="C1") for i in (1, 2)]
        session.add_all(findings)
        session.flush()
        case_id, finding_ids = case.id, [item.id for item in findings]

    counter = iter(finding_ids)
    lock = threading.Lock()

    def evaluate(session):
        with lock:
            finding_id = next(counter)
        evaluation = create_evaluation(session, case_id=case_id, finding_id=finding_id)
        return evaluation.version_number

    results = _concurrent(pg_engine, evaluate)
    assert all(tag == "ok" for tag, _ in results)
    assert sorted(value for _, value in results) == [1, 2]


def test_postgres_concurrent_associate_approval_has_one_winner(pg_engine):
    _, outcome_id, line_id = _seed_approval_workflow(pg_engine)

    def approve(session):
        decision = decide_line(session, outcome_id=outcome_id, line_outcome_id=line_id,
            stage="associate", decision="approved", auth_user_id=uuid.uuid4())
        return str(decision.id)

    results = _concurrent(pg_engine, approve)
    assert sorted(tag for tag, _ in results) == ["domain_error", "ok"]
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count(ApprovalDecision.id)).join(Approval).where(
            Approval.line_outcome_id == line_id, Approval.approval_type == "associate"
        )) == 1


def test_postgres_concurrent_manager_approval_has_one_winner(pg_engine):
    _, outcome_id, line_id = _seed_approval_workflow(
        pg_engine, original=Decimal("2000.00"), non_compliant=20, case_cost=Decimal("1000.0000")
    )
    with Session(pg_engine) as session, session.begin():
        decide_line(session, outcome_id=outcome_id, line_outcome_id=line_id,
            stage="associate", decision="approved", auth_user_id=uuid.uuid4())

    def approve(session):
        decision = decide_line(session, outcome_id=outcome_id, line_outcome_id=line_id,
            stage="manager", decision="approved", auth_user_id=uuid.uuid4())
        return str(decision.id)

    results = _concurrent(pg_engine, approve)
    assert sorted(tag for tag, _ in results) == ["domain_error", "ok"]
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count(ApprovalDecision.id)).join(Approval).where(
            Approval.line_outcome_id == line_id, Approval.approval_type == "manager"
        )) == 1


def test_postgres_r1_r2_trigger_deduplication_is_transactional(pg_engine):
    fine_id = _seed_fine(pg_engine)
    with Session(pg_engine) as session, session.begin():
        fine = session.get(FineRecord, fine_id)
        line = session.get(POLine, fine.po_line_id)
        asn = ASN(asn_number=f"PG-ASN-{uuid.uuid4()}")
        session.add(asn)
        session.flush()
        session.add_all([
            ASNLine(asn_id=asn.id, po_line_id=line.id, shipped_cases=10),
            AppointmentEvent(po_line_id=line.id, event_ts=datetime.now(timezone.utc), action="rescheduled", initiated_by="dc"),
        ])

    scan_id = f"pg-scan-{uuid.uuid4()}"
    def scan(session):
        return run_scan(session, scan_id=scan_id, fine_record_ids=[fine_id])[0]
    results = _concurrent(pg_engine, scan)
    assert all(tag == "ok" for tag, _ in results)
    assert all(value["triggered_rules"] == ["R1", "R2"] for _, value in results)
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count(InvestigationCaseTrigger.id)).where(InvestigationCaseTrigger.scan_id == scan_id)) == 2
        assert session.scalar(select(func.count(PreInvoiceScanResult.id)).where(PreInvoiceScanResult.scan_id == scan_id)) == 1


def test_postgres_dispute_submission_rolls_back_all_partial_work(pg_engine):
    with Session(pg_engine) as session, session.begin():
        supplier_a = Supplier(supplier_code=f"pg-{uuid.uuid4()}", name="A")
        supplier_b = Supplier(supplier_code=f"pg-{uuid.uuid4()}", name="B")
        session.add_all([supplier_a, supplier_b])
        session.flush()
        fine_a = _fine(session, supplier=supplier_a)
        fine_b = _fine(session, supplier=supplier_b)
        supplier_a_id, fine_a_id, fine_b_id = supplier_a.id, fine_a.id, fine_b.id

    with Session(pg_engine) as session:
        with pytest.raises(InvalidRequest, match="supplier must match"):
            with session.begin():
                submit_dispute(session, supplier_id=supplier_a_id, lines=[
                    {"fine_record_id": fine_a_id}, {"fine_record_id": fine_b_id},
                ])
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count(Dispute.id)).where(Dispute.supplier_id == supplier_a_id)) == 0
        assert session.scalar(select(func.count(DisputeLine.id)).where(DisputeLine.fine_record_id == fine_a_id)) == 0
        assert session.scalar(select(func.count(InvestigationCase.id)).where(InvestigationCase.fine_record_id == fine_a_id)) == 0


def test_postgres_constraints_reject_mismatched_case_dispute_and_duplicate_versions(pg_engine):
    fine_a_id = _seed_fine(pg_engine)
    fine_b_id = _seed_fine(pg_engine)
    with Session(pg_engine) as session, session.begin():
        fine_a, fine_b = session.get(FineRecord, fine_a_id), session.get(FineRecord, fine_b_id)
        supplier_id = session.scalar(select(PurchaseOrder.supplier_id).join(POLine).where(POLine.id == fine_a.po_line_id))
        dispute = Dispute(supplier_id=supplier_id, submitted_at=datetime.now(timezone.utc))
        case_a = InvestigationCase(fine_record=fine_a, origin="pre_invoice_scan", status="investigating")
        case_b = InvestigationCase(fine_record=fine_b, origin="pre_invoice_scan", status="investigating")
        session.add_all([dispute, case_a, case_b])
        session.flush()
        line = DisputeLine(dispute_id=dispute.id, fine_record_id=fine_a_id)
        session.add(line)
        session.flush()
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(DisputeLineCase(dispute_line_id=line.id, investigation_case_id=case_b.id, fine_record_id=fine_b_id))
                session.flush()
        finding = InvestigationFinding(investigation_case_id=case_a.id, version_number=1, cause_code="C1")
        session.add(finding)
        session.flush()
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(InvestigationFinding(investigation_case_id=case_a.id, version_number=1, cause_code="C1"))
                session.flush()
        evaluation = Evaluation(investigation_case_id=case_a.id, finding_id=finding.id,
            version_number=1, policy_version="0.1", result={}, calculation_inputs={}, calculation_outputs={})
        session.add(evaluation)
        session.flush()
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(Evaluation(investigation_case_id=case_a.id, finding_id=finding.id,
                    version_number=1, policy_version="0.1", result={}, calculation_inputs={}, calculation_outputs={}))
                session.flush()
