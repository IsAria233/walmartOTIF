import os
import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import jwt
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from app.api import InvestigationRuntime, get_runtime
from app.domain_investigation import DomainCase, DomainRequestError
from app.investigation import build_investigation_graph
from app.main import app
from test_investigation import SeedDomain, seed_finding


class ApiDomain(SeedDomain):
    def __init__(self):
        super().__init__()
        self.case = DomainCase(id=uuid4(), fine_record_id=uuid4(), status="pending")
        self.finding_id = str(uuid4())
        self.evaluation_id = str(uuid4())
        self.outcome_id = str(uuid4())
        self.fail_outcome_once = False

    def get_case(self, case_id):
        if case_id != str(self.case.id):
            raise DomainRequestError(404, "Investigation case not found")
        return self.case

    def read_intake(self, case_id, fine_record_id):
        assert str(self.get_case(case_id).fine_record_id) == fine_record_id
        return super().read_intake("SEED-02", "FINE-1002")

    def read_evidence(self, case_id, fine_record_id, sources):
        return super().read_evidence("SEED-02", "FINE-1002", sources)

    def submit_finding(self, case_id, run_id, finding, evidence):
        super().submit_finding(case_id, run_id, finding, evidence)
        return self.finding_id

    def evaluate(self, case_id, finding_id):
        super().evaluate(case_id, finding_id)
        return self.evaluation_id

    def create_outcome(self, case_id, evaluation_id):
        if self.fail_outcome_once:
            self.fail_outcome_once = False
            raise DomainRequestError(503, "Domain service is unavailable")
        super().create_outcome(case_id, evaluation_id)
        return self.outcome_id

    def read_approval_status(self, case_id, outcome_id):
        assert outcome_id == self.outcome_id
        return self.approval_status


class InvestigationApiTests(unittest.TestCase):
    def setUp(self):
        self.domain = ApiDomain()
        self.graph = build_investigation_graph(
            domain=self.domain, find_cause=seed_finding, checkpointer=InMemorySaver(),
        )
        self.model_available = True
        self.enterContext(patch.dict(os.environ, {"JWT_SECRET": "test-signing-key-for-investigation-api"}))
        self.addCleanup(app.dependency_overrides.pop, get_runtime)
        app.dependency_overrides[get_runtime] = lambda: InvestigationRuntime(
            self.graph, self.domain.get_case, lambda _: nullcontext(), self.model_available,
        )
        token = jwt.encode({
            "sub": str(uuid4()), "role": "dispute_associate",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        }, os.environ["JWT_SECRET"], algorithm="HS256")
        self.client = self.enterContext(TestClient(app, headers={"Authorization": f"Bearer {token}"}))
        self.case_body = {"case_id": str(self.domain.case.id)}
        self.key = {"Idempotency-Key": str(uuid4())}

    def test_start_read_and_resume_one_run(self):
        started = self.client.post("/investigations", json=self.case_body, headers=self.key)
        self.assertEqual(started.status_code, 201, started.text)
        run = started.json()
        self.assertEqual(run["status"], "pending_approval")
        self.assertEqual(run["fine_record_id"], str(self.domain.case.fine_record_id))
        self.assertEqual(run["finding"]["facts"][0]["evidence_ids"], ["APT-9002-2"])
        self.assertNotIn("evidence", run)
        path = f"/investigations/{run['run_id']}"
        self.assertEqual(self.client.get(path).json(), run)
        repeated = self.client.post("/investigations", json=self.case_body, headers=self.key)
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json(), run)

        rejected_payload = self.client.post(f"{path}/resume", json={"decision": "approved"})
        self.assertEqual(rejected_payload.status_code, 422)
        self.assertEqual(self.client.post(f"{path}/resume").json()["status"], "pending_approval")
        self.domain.approval_status = "pending_manager_approval"
        self.assertEqual(self.client.post(f"{path}/resume", json={}).json()["status"], "pending_manager_approval")
        self.domain.approval_status = "approved"
        self.assertEqual(self.client.post(f"{path}/resume").json()["status"], "approved")
        self.assertEqual(self.client.post(f"{path}/resume").json()["outcome_id"], run["outcome_id"])
        self.assertEqual(self.domain.writes, ["finding", "evaluation", "outcome"])

    def test_retry_recovers_from_failed_outcome_write(self):
        self.domain.fail_outcome_once = True
        first = self.client.post("/investigations", json=self.case_body, headers=self.key)
        self.assertEqual(first.status_code, 503, first.text)
        retry = self.client.post("/investigations", json=self.case_body, headers=self.key)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json()["status"], "pending_approval")
        self.assertEqual(self.domain.writes, ["finding", "evaluation", "outcome"])

    def test_blank_key_health_and_request_checks(self):
        missing = self.client.get(f"/investigations/{uuid4()}")
        self.assertEqual(missing.status_code, 404)
        anonymous = TestClient(app)
        self.addCleanup(anonymous.close)
        self.assertEqual(anonymous.post("/investigations", json=self.case_body).status_code, 401)
        self.model_available = False
        self.assertEqual(self.client.get("/health").status_code, 200)
        unavailable = self.client.post("/investigations", json=self.case_body)
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable.json()["detail"]["code"], "model_not_configured")
        self.assertFalse(self.domain.writes)
