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
                          received_cases=8, non_compliant_cases=2, system_accountability="supplier", metric="in_full",
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
    # The case and its queue row carry readable identifiers, so a list need not show UUIDs.
    row = client.get("/api/v1/investigation-cases").json()["items"][0]
    assert row["summary"] == case["summary"]
    assert row["summary"]["po_number"].startswith("PO-")
    assert (row["summary"]["supplier_name"], row["summary"]["line_number"]) == ("Supplier", 1)
    assert row["summary"]["original_amount"] == "0.60"
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


SECRET = "test-secret-with-at-least-32-bytes!!"


def bearer(role: str, sub: str | None = None) -> dict:
    import jwt
    from datetime import timedelta
    claims = {"sub": sub or str(uuid.uuid4()), "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    return {"Authorization": "Bearer " + jwt.encode(claims, SECRET, algorithm="HS256")}


@pytest.mark.real_auth
def test_every_route_needs_a_token_and_only_the_agent_records_handoffs(api, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    client, case_id = api
    assert client.get("/api/v1/fine-records").status_code == 401
    assert client.get(f"/api/v1/investigation-cases/{case_id}", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/v1/fine-records", headers=bearer("supplier")).status_code == 403
    assert client.get("/api/v1/fine-records", headers=bearer("admin")).status_code == 200

    path = f"/api/v1/internal/investigation-cases/{case_id}/handoffs/{uuid.uuid4()}"
    body = {"reason": "Gate log missing.", "details": {}}
    assert client.put(path, json=body, headers=bearer("dispute_associate")).status_code == 403
    assert client.put(path, json=body, headers=bearer("agent_service")).status_code == 200


@pytest.mark.real_auth
def test_a_reviewer_resolves_a_handed_off_case_and_it_goes_to_approval(api, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    client, case_id = api
    base, reviewer = f"/api/v1/investigation-cases/{case_id}", str(uuid.uuid4())
    as_reviewer = bearer("dispute_associate", reviewer)
    decision = {"cause_code": "C4", "rationale": "DC count sheet shows all 10 cases arrived."}

    # Not before the case is handed off, and not by a role that cannot approve.
    assert client.post(f"{base}/manual-finding", json=decision, headers=as_reviewer).status_code == 409
    handoff = f"/api/v1/internal/investigation-cases/{case_id}/handoffs/{uuid.uuid4()}"
    client.put(handoff, json={"reason": "Receipts missing.", "details": {}}, headers=bearer("agent_service"))
    assert client.post(f"{base}/manual-finding", json=decision, headers=bearer("admin")).status_code == 403
    assert client.post(f"{base}/manual-finding", json=decision, headers=bearer("agent_service")).status_code == 403
    # The fine is in-full, so an on-time cause is refused; so is an empty reason.
    assert client.post(f"{base}/manual-finding", json={**decision, "cause_code": "C1"}, headers=as_reviewer).status_code == 422
    assert client.post(f"{base}/manual-finding", json={**decision, "rationale": "  "}, headers=as_reviewer).status_code == 422
    assert client.get(base, headers=as_reviewer).json()["status"] == "handed_off"

    outcome = client.post(f"{base}/manual-finding", json=decision, headers=as_reviewer)
    assert outcome.status_code == 201, outcome.text
    line = outcome.json()["line_outcomes"][0]
    # The reviewer chose the cause; the rules engine chose the party and the amounts.
    assert (line["accountable_party"], line["outcome"], line["reversal_amount"]) == ("walmart", "waive", "0.60")
    assert client.get(base, headers=as_reviewer).json()["status"] == "awaiting_approval"
    finding = client.get(f"/api/v1/findings/{line['finding_id']}", headers=as_reviewer).json()
    assert (finding["cause_code"], finding["submitted_by_user_id"], finding["agent_run_id"]) == ("C4", reviewer, None)
    assert finding["summary"] == decision["rationale"]
    # It still needs a person's approval before the case closes.
    approval = {"line_outcome_id": line["id"], "stage": "associate", "decision": "approved"}
    assert client.post(f"/api/v1/outcomes/{outcome.json()['id']}/approvals", json=approval, headers=as_reviewer).status_code == 201
    assert client.get(base, headers=as_reviewer).json()["status"] == "closed"


@pytest.mark.real_auth
def test_a_reviewer_records_a_cause_outside_c1_c5_and_names_the_party(api, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    client, case_id = api
    base, as_reviewer = f"/api/v1/investigation-cases/{case_id}", bearer("compliance_manager")
    handoff = f"/api/v1/internal/investigation-cases/{case_id}/handoffs/{uuid.uuid4()}"
    client.put(handoff, json={"reason": "Weather claim holds.", "details": {}}, headers=bearer("agent_service"))
    other = {"cause_code": "OTHER", "rationale": "Storm alert covered the DC; shipment was on schedule."}

    # OTHER has no rule in the policy, so the reviewer must say who is accountable; C1-C5 must not.
    assert client.post(f"{base}/manual-finding", json=other, headers=as_reviewer).status_code == 422
    with_party = {"cause_code": "C4", "rationale": "x", "accountable_party": "walmart"}
    assert client.post(f"{base}/manual-finding", json=with_party, headers=as_reviewer).status_code == 422

    outcome = client.post(f"{base}/manual-finding", json={**other, "accountable_party": "walmart"}, headers=as_reviewer)
    assert outcome.status_code == 201, outcome.text
    line = outcome.json()["line_outcomes"][0]
    assert (line["accountable_party"], line["outcome"], line["corrected_amount"]) == ("walmart", "waive", "0.00")
    finding = client.get(f"/api/v1/findings/{line['finding_id']}", headers=as_reviewer).json()
    assert (finding["cause_code"], finding["reviewer_accountable_party"]) == ("OTHER", "walmart")


def test_the_agent_cannot_use_the_other_cause(api):
    client, case_id = api
    base = f"/api/v1/investigation-cases/{case_id}"
    client.patch(f"{base}/status", json={"status": "investigating"})
    finding = client.post(f"{base}/findings", json={"cause_code": "OTHER", "summary": "Weather.", "agent_run_id": str(uuid.uuid4())})
    assert finding.status_code == 201
    # Stored as written, but the rules engine will not compute a result for it.
    assert client.post(f"{base}/evaluate", json={"finding_id": finding.json()["id"]}).status_code == 409
