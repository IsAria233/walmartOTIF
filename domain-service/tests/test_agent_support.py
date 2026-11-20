"""What domain-service does for the agent: recorded handoffs and safe retries."""
from datetime import datetime, timezone
from decimal import Decimal
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.db.models import (
    DistributionCenter, FineRecord, InvestigationCase, POLine, PolicyConfiguration, PurchaseOrder, Supplier,
)
from app.db.session import get_db
from app.main import app


@compiles(JSONB, "sqlite")
def _sqlite_jsonb(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def api():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_fks(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        dc = DistributionCenter(dc_code=f"dc-{uuid.uuid4()}", name="DC", country_code="US")
        po = PurchaseOrder(po_number=f"PO-{uuid.uuid4()}", distribution_center=dc,
                           supplier=Supplier(supplier_code=f"s-{uuid.uuid4()}", name="Supplier"))
        fine = FineRecord(po_line=POLine(purchase_order=po, line_number=1), po_version_used=1, ordered_cases=10,
                          received_cases=8, non_compliant_cases=2, system_accountability="supplier",
                          original_amount=Decimal("0.60"), case_cost_snapshot=Decimal("10.0000"),
                          fine_rate=Decimal("0.030000"))
        case = InvestigationCase(fine_record=fine, origin="pre_invoice_scan", scan_rule="R2", status="pending")
        session.add_all([case, PolicyConfiguration(
            policy_version="0.1", manager_approval_threshold=Decimal("500.00"), fine_rate=Decimal("0.030000"),
            effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )])
        session.commit()
        case_id = str(case.id)

    def override_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app), case_id
    finally:
        app.dependency_overrides.clear()


def test_agent_handoff_is_recorded_once_and_shown_on_the_case(api):
    client, case_id = api
    run_id = str(uuid.uuid4())
    path = f"/api/v1/internal/investigation-cases/{case_id}/handoffs/{run_id}"
    body = {"reason": "Gate log missing.", "details": {
        "findings": {"cause": "HANDOFF", "handoff_note": "Gate log missing."}, "tools_called": ["get_asn"],
    }}

    first = client.put(path, json=body)
    assert first.status_code == 200
    assert first.json()["to_status"] == "handed_off"
    assert first.json()["handoff_details"]["tools_called"] == ["get_asn"]
    # The same run repeating the call (a retry) gets the same event back.
    assert client.put(path, json=body).json()["id"] == first.json()["id"]

    case = client.get(f"/api/v1/investigation-cases/{case_id}").json()
    assert case["status"] == "handed_off"
    assert case["handoff"]["reason"] == "Gate log missing."
    assert case["handoff"]["agent_run_id"] == run_id
    assert case["handoff"]["handoff_details"]["findings"]["cause"] == "HANDOFF"


def test_handoff_needs_a_reason_and_an_open_case(api):
    client, case_id = api
    path = f"/api/v1/internal/investigation-cases/{case_id}/handoffs/{uuid.uuid4()}"
    assert client.put(path, json={"reason": "  ", "details": {}}).status_code == 422
    missing = f"/api/v1/internal/investigation-cases/{uuid.uuid4()}/handoffs/{uuid.uuid4()}"
    assert client.put(missing, json={"reason": "x", "details": {}}).status_code == 404


def test_a_retried_agent_run_reuses_its_finding_evaluation_and_outcome(api):
    client, case_id = api
    base = f"/api/v1/investigation-cases/{case_id}"
    client.patch(f"{base}/status", json={"status": "investigating"})
    finding_body = {"cause_code": "C3", "summary": "Shipped short.", "agent_run_id": str(uuid.uuid4()), "facts": []}

    finding = client.post(f"{base}/findings", json=finding_body)
    assert finding.status_code == 201
    # The case has moved on, so a second finding would be refused; the same run gets its own back.
    assert client.post(f"{base}/findings", json=finding_body).json()["id"] == finding.json()["id"]

    evaluate = {"finding_id": finding.json()["id"], "reuse_existing": True}
    evaluation = client.post(f"{base}/evaluate", json=evaluate).json()
    assert client.post(f"{base}/evaluate", json=evaluate).json()["id"] == evaluation["id"]

    outcome_body = {"evaluation_id": evaluation["id"], "reuse_existing": True}
    outcome = client.post(f"{base}/outcome", json=outcome_body).json()
    assert client.post(f"{base}/outcome", json=outcome_body).json()["id"] == outcome["id"]
    # Without the flag the second call is still a conflict, as before.
    assert client.post(f"{base}/outcome", json={"evaluation_id": evaluation["id"]}).status_code == 409
