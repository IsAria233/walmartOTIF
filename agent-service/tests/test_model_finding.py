import json
import os
import unittest
from uuid import uuid4

import httpx
from langgraph.checkpoint.memory import InMemorySaver
from openai import OpenAI

from app.domain_evidence import DomainEvidenceReader
from app.investigation import build_investigation_graph
from app.model_finding import OpenAIFindingAnalyzer, open_finding_analyzer
from test_domain_evidence import domain_context, record_id


class TrialDomain:
    def __init__(self, reader):
        self.reader = reader
        self.writes = []

    def read_intake(self, case_id, fine_record_id):
        return self.reader.read_intake(case_id, fine_record_id, ships_to_us_dc=True)

    def read_evidence(self, case_id, fine_record_id, sources):
        return self.reader.read_evidence(case_id, fine_record_id, sources)

    def submit_finding(self, case_id, run_id, finding):
        self.writes.append("finding")
        return "trial-finding"

    def evaluate(self, case_id, finding_id):
        self.writes.append("evaluation")
        return "trial-evaluation"

    def create_outcome(self, case_id, evaluation_id):
        self.writes.append("outcome")
        return "trial-outcome"

    def read_approval_status(self, case_id, outcome_id):
        return "pending_approval"


def run_trial(number, analyzer):
    case_id, fine_id, context = domain_context(number)

    def context_response(request):
        assert request.url.path == f"/api/v1/investigation-contexts/{fine_id}"
        assert request.url.params["case_id"] == case_id
        return httpx.Response(200, json=context)

    with httpx.Client(base_url="http://domain-service:8000", transport=httpx.MockTransport(context_response)) as client:
        domain = TrialDomain(DomainEvidenceReader(client))
        graph = build_investigation_graph(domain=domain, find_cause=analyzer, checkpointer=InMemorySaver())
        run_id = str(uuid4())
        config = {"configurable": {"thread_id": run_id}}
        result = graph.invoke({"run_id": run_id, "case_id": case_id, "fine_record_id": fine_id}, config)
        return result, domain.writes


def model_response(content):
    return httpx.Response(200, json={
        "id": "resp_test", "object": "response", "created_at": 0, "model": "gpt-4.1-mini",
        "status": "completed", "output": [{
            "id": "msg_test", "type": "message", "role": "assistant", "status": "completed",
            "content": [content],
        }],
    })


def demo_finding(cause_code, evidence_ids):
    return {
        "cause_code": cause_code, "summary": "The evidence supports this cause", "confidence": 0.95,
        "facts": [{"fact_key": "check", "fact_value": "Evidence reviewed", "evidence_ids": evidence_ids}],
        "handoff_reason": None,
    }


class ModelFindingTests(unittest.TestCase):
    def sdk(self, respond):
        http = httpx.Client(transport=httpx.MockTransport(respond))
        client = OpenAI(api_key="test-only", base_url="https://example.test/v1", http_client=http, max_retries=0)
        self.addCleanup(client.close)
        return OpenAIFindingAnalyzer(client)

    def test_structured_requests_and_valid_results_for_both_seed_cases(self):
        for number, cause_code, evidence_ids in (
            (2, "C2", [record_id("APT-9002-2")]),
            (4, "C4", [record_id("RCV-70014"), record_id("RCV-70019")]),
        ):
            with self.subTest(seed=number):
                requests = []

                def respond(request):
                    self.assertEqual((request.method, request.url.path), ("POST", "/v1/responses"))
                    body = json.loads(request.content)
                    requests.append(body)
                    return model_response({
                        "type": "output_text", "text": json.dumps(demo_finding(cause_code, evidence_ids)), "annotations": [],
                    })

                result, writes = run_trial(number, self.sdk(respond))
                self.assertEqual(result["status"], "pending_approval")
                self.assertEqual(result["finding"]["cause_code"], cause_code)
                self.assertEqual(result["finding"]["facts"][0]["evidence_ids"], evidence_ids)
                self.assertEqual(writes, ["finding", "evaluation", "outcome"])
                self.assertEqual(len(requests), 1)
                body = requests[0]
                self.assertFalse(body["store"])
                self.assertTrue(body["text"]["format"]["strict"])
                prompt = json.loads(body["input"])
                self.assertEqual(set(prompt), {"case", "candidate_causes", "evidence"})
                self.assertNotIn("po_line_id", prompt["case"])
                if number == 2:
                    self.assertEqual(prompt["case"]["mabd"], "2026-10-14")
                    self.assertEqual(prompt["case"]["standard_transit_days"], 2)
                    self.assertEqual(set(prompt["evidence"]), {"asn", "appointment_history", "gate_log"})
                else:
                    self.assertEqual(prompt["case"]["fine_received_cases"], 1380)
                    self.assertEqual(set(prompt["evidence"]), {"asn", "po_versions", "receiving"})

    def test_model_handoff_and_invalid_citation_do_not_write(self):
        for finding in (
            {**demo_finding(None, []), "handoff_reason": "Evidence conflicts"},
            demo_finding("C2", ["fabricated-evidence-id"]),
        ):
            with self.subTest(finding=finding):
                analyzer = self.sdk(lambda request: model_response({
                    "type": "output_text", "text": json.dumps(finding), "annotations": [],
                }))
                result, writes = run_trial(2, analyzer)
                self.assertEqual(result["result"]["status"], "needs_review")
                self.assertFalse(writes)

    def test_refusal_and_api_error_handoff(self):
        for response, error in (
            (model_response({"type": "refusal", "refusal": "Cannot produce a finding"}), "complete structured finding"),
            (httpx.Response(503, json={"error": {"message": "Service unavailable"}}), "HTTP 503"),
        ):
            with self.subTest(error=error):
                result, writes = run_trial(2, self.sdk(lambda request: response))
                self.assertEqual(result["result"]["status"], "needs_review")
                self.assertIn(error, result["result"]["handoff_reason"])
                self.assertFalse(writes)

    @unittest.skipUnless(os.getenv("RUN_OPENAI_EVAL") == "1", "Live OpenAI trial is opt-in")
    def test_live_openai_seed_cases(self):
        with open_finding_analyzer() as analyzer:
            for number, cause, required_citations in (
                (2, "C2", {record_id("APT-9002-2")}),
                (4, "C4", {record_id("RCV-70014"), record_id("RCV-70019")}),
            ):
                with self.subTest(seed=number):
                    result, _ = run_trial(number, analyzer)
                    self.assertEqual(result["status"], "pending_approval", result.get("result"))
                    finding = result["finding"]
                    self.assertEqual(finding["cause_code"], cause)
                    cites = {ref for fact in finding["facts"] for ref in fact["evidence_ids"]}
                    self.assertTrue(required_citations.issubset(cites))
