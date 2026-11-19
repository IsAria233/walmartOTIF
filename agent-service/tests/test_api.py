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
        self.handoff_id = str(uuid4())
        self.lose_handoff_response = False
        self.handoff_calls = 0

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

    def record_handoff(self, case_id, run_id, reason, details):
        self.handoff_calls += 1
        if not self.handoffs:
            super().record_handoff(case_id, run_id, reason, details)
        if self.lose_handoff_response:
            self.lose_handoff_response = False
            raise DomainRequestError(503, "Lost handoff response")
        return self.handoff_id


class InvestigationApiTests(unittest.TestCase):
    def setUp(self):
        self.domain = ApiDomain()
        self.graph = build_investigation_graph(
            domain=self.domain, find_cause=seed_finding, checkpointer=InMemorySaver(),
        )
        self.model_available = True
        self.langfuse = None
        self.enterContext(patch.dict(os.environ, {"JWT_SECRET": "test-signing-key-for-investigation-api"}))
        self.addCleanup(app.dependency_overrides.pop, get_runtime)
        app.dependency_overrides[get_runtime] = lambda: InvestigationRuntime(
            self.graph, self.domain.get_case, lambda _: nullcontext(), self.model_available,
            langfuse=self.langfuse,
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

    def test_retry_recovers_after_domain_saved_handoff(self):
        self.domain.require_review = True
        self.domain.lose_handoff_response = True
        first = self.client.post("/investigations", json=self.case_body, headers=self.key)
        self.assertEqual(first.status_code, 503, first.text)
        retry = self.client.post("/investigations", json=self.case_body, headers=self.key)
        self.assertEqual(retry.status_code, 200, retry.text)
        run = retry.json()
        self.assertEqual(run["status"], "needs_review")
        self.assertEqual(run["handoff_id"], self.domain.handoff_id)
        self.assertIsNone(run["outcome_id"])
        self.assertEqual(self.domain.writes, ["finding", "evaluation"])
        self.assertEqual(self.domain.handoff_calls, 2)
        self.assertEqual(len(self.domain.handoffs), 1)
        self.assertEqual(self.client.get(f"/investigations/{run['run_id']}").json(), run)

    def test_langfuse_groups_start_resume_and_handoff_without_raw_case_content(self):
        from langfuse import Langfuse
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        exporter = InMemorySpanExporter()
        self.langfuse = Langfuse(
            public_key=f"pk-lf-local-{uuid4()}", secret_key="sk-lf-local-test",
            tracer_provider=TracerProvider(), span_exporter=exporter, flush_at=1,
        )
        self.addCleanup(self.langfuse.shutdown)
        first = self.client.post("/investigations", json=self.case_body, headers=self.key)
        self.assertEqual(first.status_code, 201, first.text)
        self.domain.approval_status = "approved"
        self.client.post(f"/investigations/{first.json()['run_id']}/resume").raise_for_status()
        self.domain.require_review = True
        handoff = self.client.post("/investigations", json=self.case_body)
        self.assertEqual(handoff.json()["status"], "needs_review")

        self.langfuse.flush()
        spans = exporter.get_finished_spans()
        span_names = {span.name for span in spans}
        self.assertTrue({"workflow.investigate", "workflow.findings", "workflow.approval_pause", "workflow.finalize"}.issubset(span_names))
        starts = [span for span in spans if span.name == "investigation.start"]
        (resumed,) = [span for span in spans if span.name == "investigation.resume"]
        (original,) = [span for span in starts if span.context.trace_id == resumed.context.trace_id]
        self.assertTrue(any(
            span.name == "workflow.investigate" and span.parent.span_id == original.context.span_id
            for span in spans
        ))
        self.assertEqual(len({span.context.trace_id for span in starts}), 2)
        attributes = " ".join(str(dict(span.attributes)) for span in spans)
        self.assertIn("policy_unavailable", attributes)
        self.assertNotIn("APT-9002", attributes)
        self.assertNotIn("rescheduled the delivery appointment", attributes)
