from datetime import date, datetime, timezone
from decimal import Decimal
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.db.models import (
    ASN, ASNLine, AppointmentEvent, Delivery, DeliveryLine, Dispute,
    DistributionCenter, EvidenceRecord, FineRecord, GateLog, InvestigationCaseTrigger,
    POLine, POLineVersion, PreInvoiceScanResult, PurchaseOrder,
    PolicyConfiguration, ReceivingRecord, Supplier, WeatherAlert,
)
from app.db.session import get_db
from app.main import app


@compiles(JSONB, "sqlite")
def _sqlite_jsonb(type_, compiler, **kw):
    return "JSON"


def test_case_and_dispute_api_contracts_and_pagination(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_fks(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        supplier = Supplier(supplier_code=f"api-{uuid.uuid4()}", name="Supplier")
        other_supplier = Supplier(supplier_code=f"api-other-{uuid.uuid4()}", name="Other")
        dc = DistributionCenter(dc_code=f"api-{uuid.uuid4()}", name="DC")
        po = PurchaseOrder(po_number=f"API-{uuid.uuid4()}", supplier=supplier, distribution_center=dc)
        line = POLine(purchase_order=po, line_number=1)
        fine = FineRecord(po_line=line, po_version_used=1, ordered_cases=10,
            received_cases=8, non_compliant_cases=2, system_accountability="supplier",
            original_amount=Decimal("20.00"), case_cost_snapshot=Decimal("10.0000"), fine_rate=Decimal("0.030000"))
        line2 = POLine(purchase_order=po, line_number=2)
        fine2 = FineRecord(po_line=line2, po_version_used=1, ordered_cases=10,
            received_cases=10, non_compliant_cases=0, system_accountability="supplier",
            original_amount=Decimal("0.00"), case_cost_snapshot=Decimal("10.0000"), fine_rate=Decimal("0.030000"))
        session.add(AppointmentEvent(po_line=line, event_ts=datetime.now(timezone.utc), action="rescheduled", initiated_by="dc"))
        asn = ASN(asn_number=f"ASN-{uuid.uuid4()}")
        asn_line = ASNLine(asn=asn, po_line=line, shipped_cases=10)
        delivery = Delivery(distribution_center=dc, delivery_number=f"DEL-{uuid.uuid4()}", actual_arrival_ts=datetime.now(timezone.utc))
        delivery_line = DeliveryLine(asn_line=asn_line, delivery=delivery, allocated_cases=10)
        version = POLineVersion(po_line=line, version_number=1, ordered_cases=10, issued_at=datetime.now(timezone.utc))
        session.add_all([
            supplier, other_supplier, dc, po, line, line2, fine, fine2, asn,
            asn_line, delivery, delivery_line, version,
            GateLog(delivery=delivery, check_in_ts=datetime.now(timezone.utc), gate_identifier="G1"),
            ReceivingRecord(delivery_line=delivery_line, received_at=datetime.now(timezone.utc), received_cases=8),
            WeatherAlert(distribution_center=dc, external_alert_id=f"W-{uuid.uuid4()}", alert_date=date.today(), alert_type="storm"),
            PolicyConfiguration(policy_version="0.1", effective_from=datetime(1970, 1, 1, tzinfo=timezone.utc), manager_approval_threshold=Decimal("500.00"), fine_rate=Decimal("0.030000")),
            EvidenceRecord(evidence_type="receipt", external_id=f"E-{uuid.uuid4()}", snapshot={"received_cases": 8}),
        ])
        session.commit()
        fine_id, fine2_id, supplier_id, other_supplier_id, line_id, line2_id = fine.id, fine2.id, supplier.id, other_supplier.id, line.id, line2.id
        po_id, asn_id, delivery_id, dc_id = po.id, asn.id, delivery.id, dc.id
        evidence_id = session.query(EvidenceRecord).one().id

    def override_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/investigation-cases", json={
                "fine_record_id": str(fine_id), "origin": "pre_invoice_scan"
            })
            assert response.status_code == 201, response.text
            case_id = response.json()["id"]
            reused = client.post("/api/v1/investigation-cases", json={
                "fine_record_id": str(fine_id), "origin": "pre_invoice_scan"
            })
            assert reused.status_code == 200
            assert reused.json()["id"] == case_id
            assert client.patch(f"/api/v1/investigation-cases/{case_id}/status", json={"status": "investigating"}).status_code == 200
            assert client.get(f"/api/v1/investigation-cases/{case_id}").status_code == 200
            finding = client.post(f"/api/v1/investigation-cases/{case_id}/findings", json={
                "summary": "reviewed", "cause_code": "C1",
                "facts": [{"fact_key": "receipt", "fact_value": "8", "evidence_ids": [str(evidence_id)]}],
            })
            assert finding.status_code == 201, finding.text
            assert finding.json()["version_number"] == 1
            finding_id = finding.json()["id"]
            assert client.get(f"/api/v1/investigation-cases/{case_id}/findings").status_code == 200
            assert client.get(f"/api/v1/findings/{finding_id}").status_code == 200
            queue = client.get("/api/v1/investigation-cases?page=1&page_size=1&sort_by=created_at")
            assert queue.status_code == 200
            assert queue.json()["total"] == 1
            assert "__table__" not in queue.text
            filtered_queue = client.get(
                f"/api/v1/investigation-cases?status=findings_submitted&origin=pre_invoice_scan&fine_record_id={fine_id}&supplier_id={supplier_id}&created_from=2000-01-01T00:00:00Z&created_to=2100-01-01T00:00:00Z&sort_by=status&sort_order=asc"
            )
            assert filtered_queue.status_code == 200, filtered_queue.text
            assert filtered_queue.json()["total"] == 1
            fine_response = client.get(f"/api/v1/fine-records/{fine_id}")
            assert fine_response.status_code == 200
            assert fine_response.json()["original_amount"] == "20.00"
            auth_unavailable = client.post(f"/api/v1/outcomes/{uuid.uuid4()}/approvals", json={
                "line_outcome_id": str(uuid.uuid4()), "stage": "associate", "decision": "approved"
            })
            assert auth_unavailable.status_code == 503
            assert auth_unavailable.json()["error"]["code"] == "identity_unavailable"
            fine_response = client.get(f"/api/v1/fine-records/{fine_id}")
            assert fine_response.status_code == 200
            assert fine_response.json()["original_amount"] == "20.00"
            auth_unavailable = client.post(f"/api/v1/outcomes/{uuid.uuid4()}/approvals", json={
                "line_outcome_id": str(uuid.uuid4()), "stage": "associate", "decision": "approved"
            })
            assert auth_unavailable.status_code == 503
            assert auth_unavailable.json()["error"]["code"] == "identity_unavailable"

            dispute = client.post("/api/v1/disputes", json={
                "supplier_id": str(supplier_id),
                "lines": [{"fine_record_id": str(fine_id), "amount_disputed": "20.00"}],
                "attachments": [{"fine_record_id": str(fine_id), "filename": "proof.pdf"}],
            })
            assert dispute.status_code == 201, dispute.text
            assert len(dispute.json()["lines"]) == 1
            assert dispute.json()["attachments"][0]["dispute_line_id"] == dispute.json()["lines"][0]["id"]
            bad_dispute = client.post("/api/v1/disputes", json={
                "supplier_id": str(other_supplier_id), "lines": [{"fine_record_id": str(fine_id)}]
            })
            assert bad_dispute.status_code == 422
            with Session(engine) as session:
                assert session.query(Dispute).count() == 1
            failed_attachment = client.post("/api/v1/disputes", json={
                "supplier_id": str(supplier_id), "lines": [{"fine_record_id": str(fine_id)}],
                "attachments": [{"dispute_line_id": str(uuid.uuid4()), "filename": "invalid.pdf"}],
            })
            assert failed_attachment.status_code == 422
            with Session(engine) as session:
                assert session.query(Dispute).count() == 1
            scan_body = {"scan_id": "scan-test-1", "fine_record_ids": [str(fine_id)]}
            first_scan = client.post("/api/v1/pre-invoice-scans/run", json=scan_body)
            repeated_scan = client.post("/api/v1/pre-invoice-scans/run", json=scan_body)
            assert first_scan.status_code == 200, first_scan.text
            scan_result = first_scan.json()["results"][0]
            assert scan_result["triggered_rules"] == ["R1", "R2"]
            assert scan_result["case_action"] == "reused_existing"
            with Session(engine) as session:
                assert session.query(InvestigationCaseTrigger).filter_by(scan_id="scan-test-1").count() == 2
                assert session.query(PreInvoiceScanResult).filter_by(scan_id="scan-test-1").count() == 1
            assert repeated_scan.json()["results"][0]["case_id"] == scan_result["case_id"]
            skipped_body = {"scan_id": "scan-test-skipped", "fine_record_ids": [str(fine2_id)]}
            skipped_once = client.post("/api/v1/pre-invoice-scans/run", json=skipped_body)
            assert skipped_once.json()["results"][0]["case_action"] == "skipped"
            with Session(engine) as session:
                session.add(AppointmentEvent(po_line_id=line2_id, event_ts=datetime.now(timezone.utc), action="rescheduled", initiated_by="dc"))
                session.commit()
            skipped_again = client.post("/api/v1/pre-invoice-scans/run", json=skipped_body)
            assert skipped_again.json()["results"][0]["case_action"] == "skipped"
            assert skipped_again.json()["results"][0]["triggered_rules"] == []
            before_context = client.get(f"/api/v1/investigation-contexts/{fine_id}")
            assert before_context.status_code == 200, before_context.text
            assert before_context.json()["active_case"]["id"] == case_id
            assert len(before_context.json()["case_history"]) == 1
            mismatch = client.get(f"/api/v1/investigation-contexts/{fine_id}?case_id={uuid.uuid4()}")
            assert mismatch.status_code == 422
            assert client.patch(f"/api/v1/investigation-cases/{case_id}/status", json={"status": "closed"}).status_code == 409
            assert client.get("/api/v1/investigation-cases/not-a-uuid").status_code == 422

            # Exercise every registered operation through FastAPI's actual
            # response_model validation, including typed nested/paginated DTOs.
            dispute_id = dispute.json()["dispute"]["id"]
            assert client.get(f"/api/v1/disputes/{dispute_id}").status_code == 200
            evaluation = client.post(f"/api/v1/investigation-cases/{case_id}/evaluate", json={"finding_id": finding_id})
            assert evaluation.status_code == 201, evaluation.text
            evaluation_id = evaluation.json()["id"]
            assert client.get(f"/api/v1/investigation-cases/{case_id}/evaluations").status_code == 200
            assert client.get(f"/api/v1/evaluations/{evaluation_id}").status_code == 200
            outcome = client.post(f"/api/v1/investigation-cases/{case_id}/outcome", json={"evaluation_id": evaluation_id})
            assert outcome.status_code == 201, outcome.text
            assert len(outcome.json()["line_outcomes"]) == 1
            outcome_id = outcome.json()["id"]
            assert client.get(f"/api/v1/investigation-cases/{case_id}/outcome").status_code == 200
            monkeypatch.setattr("app.api.routers.authenticated_user", lambda request: uuid.uuid4())
            monkeypatch.setattr("app.api.routers.authenticated_role", lambda request: "compliance_manager")
            line_outcome_id = outcome.json()["line_outcomes"][0]["id"]
            approval = client.post(f"/api/v1/outcomes/{outcome_id}/approvals", json={
                "line_outcome_id": line_outcome_id, "stage": "associate", "decision": "approved"
            })
            assert approval.status_code == 201, approval.text
            assert client.get(f"/api/v1/outcomes/{outcome_id}/approvals").status_code == 200
            populated_context = client.get(f"/api/v1/investigation-contexts/{fine_id}")
            assert populated_context.status_code == 200, populated_context.text
            assert populated_context.json()["case_context"][0]["evidence_context"][0]["evidence_links"][0]["evidence"]["id"] == str(evidence_id)
            assert populated_context.json()["case_context"][0]["outcomes"][0]["line_outcomes"]

            for path in [
                f"/api/v1/suppliers/{supplier_id}",
                f"/api/v1/purchase-orders/{po_id}",
                f"/api/v1/purchase-orders/{po_id}/lines",
                f"/api/v1/po-lines/{line_id}/versions",
                f"/api/v1/asns/{asn_id}",
                f"/api/v1/po-lines/{line_id}/asns",
                f"/api/v1/po-lines/{line_id}/appointments",
                f"/api/v1/deliveries/{delivery_id}",
                f"/api/v1/deliveries/{delivery_id}/gate-logs",
                f"/api/v1/po-lines/{line_id}/receiving-records",
                f"/api/v1/distribution-centers/{dc_id}/weather-alerts",
                "/api/v1/fine-records",
                f"/api/v1/fine-records/{fine_id}/disputes",
            ]:
                route_response = client.get(path)
                assert route_response.status_code == 200, f"{path}: {route_response.text}"
            empty_context = client.get(f"/api/v1/investigation-contexts/{fine2_id}")
            assert empty_context.status_code == 200
            assert empty_context.json()["active_case"] is None
            assert client.get(f"/api/v1/fine-records/{fine_id}").json()["created_at"].endswith("Z")
            assert client.get("/api/v1/fine-records?page=0").status_code == 422

            # Foreign workflow identifiers are rejected at route boundaries.
            second_case = client.post("/api/v1/investigation-cases", json={"fine_record_id": str(fine2_id), "origin": "pre_invoice_scan"})
            assert second_case.status_code == 201
            second_case_id = second_case.json()["id"]
            assert client.patch(f"/api/v1/investigation-cases/{second_case_id}/status", json={"status": "investigating"}).status_code == 200
            second_finding = client.post(f"/api/v1/investigation-cases/{second_case_id}/findings", json={"cause_code": "C1"})
            assert second_finding.status_code == 201
            foreign_evaluation = client.post(f"/api/v1/investigation-cases/{second_case_id}/evaluate", json={"finding_id": finding_id})
            assert foreign_evaluation.status_code == 422
            foreign_outcome = client.post(f"/api/v1/investigation-cases/{second_case_id}/outcome", json={"evaluation_id": evaluation_id})
            assert foreign_outcome.status_code == 422

            missing = str(uuid.uuid4())
            for path in [
                f"/api/v1/investigation-cases/{missing}", f"/api/v1/disputes/{missing}",
                f"/api/v1/findings/{missing}", f"/api/v1/evaluations/{missing}",
                f"/api/v1/investigation-cases/{missing}/evaluations",
                f"/api/v1/investigation-cases/{missing}/outcome",
                f"/api/v1/outcomes/{missing}/approvals", f"/api/v1/investigation-contexts/{missing}",
                f"/api/v1/fine-records/{missing}", f"/api/v1/fine-records/{missing}/disputes",
                f"/api/v1/suppliers/{missing}", f"/api/v1/purchase-orders/{missing}",
                f"/api/v1/purchase-orders/{missing}/lines", f"/api/v1/po-lines/{missing}/versions",
                f"/api/v1/asns/{missing}", f"/api/v1/po-lines/{missing}/asns",
                f"/api/v1/po-lines/{missing}/appointments", f"/api/v1/deliveries/{missing}",
                f"/api/v1/deliveries/{missing}/gate-logs", f"/api/v1/po-lines/{missing}/receiving-records",
                f"/api/v1/distribution-centers/{missing}/weather-alerts",
            ]:
                assert client.get(path).status_code == 404, path
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_all_registered_api_operations_have_explicit_openapi_response_contracts():
    from app.api.routers import router
    from app.main import app

    # FastAPI versions may keep include_router as a lazy router entry in
    # app.routes; inspect the actual registered APIRoute objects directly.
    operations = router.routes
    assert len(operations) == 32
    assert all(route.response_model is not None for route in operations)
    document = app.openapi()
    openapi_operations = [
        (method, path, operation)
        for path, path_item in document["paths"].items() if path.startswith("/api/v1")
        for method, operation in path_item.items()
        if method in {"get", "post", "patch", "put", "delete"}
    ]
    assert len(openapi_operations) == 32
    assert all("200" in operation["responses"] or "201" in operation["responses"] for _, _, operation in openapi_operations)
