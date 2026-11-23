"""HTTP entry points: sign-in required, repeat-safe start, read, resume."""
from datetime import datetime, timedelta, timezone
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

from app.graph import Investigator
from app.main import Runtime, app
from tests.test_graph import FakeDomain, context, findings, scripted, turn

SECRET = "k" * 48
CASE = str(uuid.uuid4())


def bearer(role="dispute_associate", minutes=5, key=SECRET):
    claims = {"sub": str(uuid.uuid4()), "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes)}
    return {"Authorization": f"Bearer {jwt.encode(claims, key, algorithm='HS256')}"}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    domain = FakeDomain(context())
    llm = scripted(turn(("get_asn", {}), ("submit_findings", findings())))
    app.state.runtime = Runtime(Investigator(domain, llm), domain, checkpoint_dsn=None)
    app.state.model_available = True
    return TestClient(app), domain, llm


def test_every_investigation_endpoint_needs_a_valid_internal_token(api):
    client, _, llm = api
    run = f"/investigations/{uuid.uuid4()}"
    for headers in ({}, bearer(minutes=-5), bearer(key="x" * 48), bearer(role="supplier")):
        assert client.post("/investigations", json={"case_id": CASE}, headers=headers).status_code == 401
        assert client.get(run, headers=headers).status_code == 401
        assert client.post(f"{run}/resume", headers=headers).status_code == 401
    assert llm.seen == []


def test_start_read_and_resume_after_approval(api):
    client, domain, _ = api
    started = client.post("/investigations", json={"case_id": CASE}, headers=bearer())
    assert started.status_code == 201
    run = started.json()
    assert (run["status"], run["paused_for_approval"]) == ("awaiting_approval", True)
    assert client.get(f"/investigations/{run['run_id']}", headers=bearer("admin")).json() == run

    domain.approval = "approved"
    resumed = client.post(f"/investigations/{run['run_id']}/resume", headers=bearer("compliance_manager"))
    assert resumed.json()["status"] == "approved"
    assert client.get(f"/investigations/{uuid.uuid4()}", headers=bearer()).status_code == 404


def test_repeating_a_start_with_the_same_idempotency_key_returns_the_same_run(api):
    client, _, llm = api
    headers = {**bearer(), "Idempotency-Key": str(uuid.uuid4())}
    first = client.post("/investigations", json={"case_id": CASE}, headers=headers)
    second = client.post("/investigations", json={"case_id": CASE}, headers=headers)
    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["run_id"] == first.json()["run_id"]
    assert len(llm.seen) == 1


def test_a_case_that_is_not_open_cannot_start_a_new_investigation(api):
    client, domain, llm = api
    domain.status = "awaiting_approval"
    assert client.post("/investigations", json={"case_id": CASE}, headers=bearer()).status_code == 409
    assert llm.seen == []


def test_a_second_request_for_a_case_is_refused_while_one_is_running(api):
    client, _, _ = api
    runtime = app.state.runtime
    with runtime.lock_case(uuid.UUID(CASE)):
        assert client.post("/investigations", json={"case_id": CASE}, headers=bearer()).status_code == 409


def test_domain_calls_carry_a_short_lived_agent_service_token(monkeypatch):
    import httpx
    import jwt

    from app.domain_client import DomainClient

    secret = "test-secret-with-at-least-32-bytes!!"
    monkeypatch.setenv("JWT_SECRET", secret)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("Authorization", ""))
        return httpx.Response(200, json={"id": "case-1"})

    client = DomainClient(client=httpx.Client(transport=httpx.MockTransport(handler), base_url="http://domain/api/v1"))
    client.get_case("case-1")
    claims = jwt.decode(seen[0].removeprefix("Bearer "), secret, algorithms=["HS256"])
    # Its own role, not a user's: domain-service lets it do case work and never lets it approve.
    assert claims["role"] == "agent_service"
