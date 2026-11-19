import json
import unittest
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

import httpx
from langgraph.checkpoint.memory import InMemorySaver

from app.domain_evidence import DomainEvidenceReader
from app.investigation import EvidenceReadError, Finding, build_investigation_graph
from test_investigation import SEED_CASE, SeedDomain


def record_id(label):
    return str(uuid5(NAMESPACE_URL, label))


def domain_context(case_number):
    case_name = f"SEED-{case_number:02}"
    seed = json.loads(SEED_CASE.with_name(f"{case_name}_input.json").read_text())
    case_id = record_id(case_name)
    fine_id = record_id(seed["fine_record"]["fine_id"])
    po_line_id = record_id(f"{case_name}-po-line")
    asn_id = record_id(seed["asn"]["asn_id"])
    asn_line = {
        "id": record_id(f"{case_name}-asn-line"), "asn_id": asn_id,
        "po_line_id": po_line_id, "shipped_cases": seed["asn"]["shipped_cases"],
    }
    delivery_id = record_id(f"{case_name}-delivery")
    delivery_line_id = record_id(f"{case_name}-delivery-line")
    context = {
        "fine_record": {**seed["fine_record"], "id": fine_id, "po_line_id": po_line_id},
        "purchase_order": {"freight_terms": seed["po"]["freight_terms"], "channel": seed["po"]["channel"]},
        "po_line": {
            "id": po_line_id, "mabd": seed["po"]["mabd"],
            "standard_transit_days": seed["po"]["standard_transit_days"],
        },
        "asns": [{
            "asn": {"id": asn_id, "asn_number": seed["asn"]["asn_id"], "ship_ts": seed["asn"]["ship_ts"]},
            "lines": [asn_line],
        }],
        "appointments": [{
            "id": record_id(event["event_id"]), "po_line_id": po_line_id,
            "event_ts": event["ts"], "appointment_ts": event["slot"],
            "action": event["action"], "initiated_by": event["by"].lower(),
        } for event in seed["appointment_history"]],
        "po_line_versions": [{
            "id": record_id(f"{case_name}-po-version-{version['version']}"), "po_line_id": po_line_id,
            "version_number": version["version"], "issued_at": version["issued_at"],
            "ordered_cases": version["ordered_cases"],
        } for version in seed["po"]["versions"]],
        "deliveries": [{
            "delivery": {"id": delivery_id},
            "delivery_line": {"id": delivery_line_id, "delivery_id": delivery_id, "asn_line_id": asn_line["id"]},
            "asn_line": asn_line,
            "gate_logs": [{
                "id": record_id(row["gate_id"]), "delivery_id": delivery_id, "check_in_ts": row["check_in"],
            } for row in seed["gate_log"]],
            "receiving_records": [{
                "id": record_id(row["receipt_id"]), "delivery_line_id": delivery_line_id,
                "received_at": row["ts"], "received_cases": row["cases"], "exception_code": row["exception"],
            } for row in seed["receiving"]],
        }],
    }
    return case_id, fine_id, context


class DomainEvidenceTests(unittest.TestCase):
    def client(self, case_id, fine_id, context):
        def respond(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.path, f"/api/v1/investigation-contexts/{fine_id}")
            self.assertEqual(dict(request.url.params), {"case_id": case_id})
            requests.append(request)
            return httpx.Response(200, json=context)

        requests = []
        client = httpx.Client(base_url="http://domain-service:8000", transport=httpx.MockTransport(respond))
        self.addCleanup(client.close)
        return DomainEvidenceReader(client), requests

    def test_on_time_evidence_uses_one_request_and_keeps_appointment_citation(self):
        case_id, fine_id, context = domain_context(2)
        context["deliveries"].append(deepcopy(context["deliveries"][0]))
        reader, requests = self.client(case_id, fine_id, context)
        evidence = reader.read_evidence(case_id, fine_id, ["asn", "appointment_history", "gate_log"])
        self.assertEqual(len(requests), 1)
        self.assertEqual(set(evidence), {"asn", "appointment_history", "gate_log"})
        self.assertEqual(evidence["asn"][0]["facts"]["shipped_cases"], 1200)
        dc_change = evidence["appointment_history"][1]
        self.assertEqual(dc_change["record_id"], record_id("APT-9002-2"))
        self.assertEqual(dc_change["facts"]["initiated_by"], "dc")
        self.assertEqual(len(evidence["gate_log"]), 1)
        self.assertEqual(evidence["gate_log"][0]["facts"]["delivery_id"], context["deliveries"][0]["delivery"]["id"])

    def test_in_full_evidence_keeps_late_receipt_and_excludes_other_order_lines(self):
        case_id, fine_id, context = domain_context(4)
        delivery = context["deliveries"][0]
        wrong_line = record_id("unrelated-po-line")
        alien_delivery = deepcopy(delivery)
        alien_delivery["asn_line"]["po_line_id"] = wrong_line
        alien_delivery["receiving_records"][0]["id"] = record_id("unrelated-receipt")
        context["deliveries"].append(alien_delivery)
        context["po_line_versions"].append({**context["po_line_versions"][0], "po_line_id": wrong_line})
        reader, requests = self.client(case_id, fine_id, context)

        evidence = reader.read_evidence(case_id, fine_id, ["asn", "po_versions", "receiving"])
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(evidence["po_versions"]), 1)
        self.assertEqual(evidence["po_versions"][0]["facts"]["issued_at"], "2026-10-08T14:00")
        receipts = evidence["receiving"]
        self.assertEqual([receipt["facts"]["received_cases"] for receipt in receipts], [1380, 120])
        self.assertEqual(receipts[1]["record_id"], record_id("RCV-70019"))
        self.assertEqual(receipts[1]["facts"]["received_at"], "2026-10-22T09:30")
        self.assertEqual({receipt["facts"]["delivery_line_id"] for receipt in receipts}, {delivery["delivery_line"]["id"]})

    def test_successful_empty_appointment_history_is_preserved(self):
        case_id, fine_id, context = domain_context(2)
        context["appointments"] = []
        reader, _ = self.client(case_id, fine_id, context)
        self.assertEqual(reader.read_evidence(case_id, fine_id, ["appointment_history"]), {"appointment_history": []})

    def test_domain_errors_are_not_reported_as_empty_evidence(self):
        case_id, fine_id, _ = domain_context(2)
        for response, diagnostic in (
            (httpx.Response(503), "HTTP 503"),
            (httpx.Response(200, json={}), "invalid shape"),
        ):
            with self.subTest(diagnostic=diagnostic):
                with httpx.Client(
                    base_url="http://domain-service:8000", transport=httpx.MockTransport(lambda request: response),
                ) as client:
                    with self.assertRaisesRegex(EvidenceReadError, diagnostic):
                        DomainEvidenceReader(client).read_evidence(case_id, fine_id, ["asn"])

    def test_graph_investigate_uses_the_http_reader_and_hands_off_on_failure(self):
        case_id, fine_id, context = domain_context(2)
        reader, requests = self.client(case_id, fine_id, context)

        class FixtureDomain(SeedDomain):
            def read_intake(self, selected_case_id, selected_fine_id):
                assert (selected_case_id, selected_fine_id) == (case_id, fine_id)
                return super().read_intake("SEED-02", "FINE-1002")

            def read_evidence(self, case_id, fine_record_id, sources):
                raise AssertionError("The graph should use the HTTP evidence reader")

            def read_approval_status(self, case_id, outcome_id):
                return self.approval_status

        def find_cause(case, plan, evidence):
            dc_change = next(row for row in evidence["appointment_history"] if row["facts"]["initiated_by"] == "dc")
            return Finding(cause_code="C2", summary="The DC rescheduled delivery", confidence=1, facts=[{
                "fact_key": "dc_rescheduled", "fact_value": dc_change["facts"]["appointment_ts"],
                "evidence_ids": [dc_change["record_id"]],
            }])

        domain = FixtureDomain()
        graph = build_investigation_graph(
            domain=domain, find_cause=find_cause, checkpointer=InMemorySaver(), evidence_reader=reader,
        )
        inputs = {"run_id": record_id("run-1"), "case_id": case_id, "fine_record_id": fine_id}
        result = graph.invoke(inputs, {"configurable": {"thread_id": inputs["run_id"]}})
        self.assertEqual(result["finding"]["facts"][0]["evidence_ids"], [record_id("APT-9002-2")])
        self.assertEqual(result["status"], "pending_approval")
        self.assertEqual(len(requests), 1)

        def timeout(request):
            raise httpx.ReadTimeout("Domain did not respond", request=request)

        domain = FixtureDomain()
        with httpx.Client(base_url="http://domain-service:8000", transport=httpx.MockTransport(timeout)) as client:
            graph = build_investigation_graph(
                domain=domain, find_cause=find_cause, checkpointer=InMemorySaver(), evidence_reader=DomainEvidenceReader(client),
            )
            result = graph.invoke(inputs, {"configurable": {"thread_id": inputs["run_id"]}})
        self.assertEqual(result["result"]["status"], "needs_review")
        self.assertEqual(result["result"]["handoff_reason"], "Domain evidence request failed")
        self.assertFalse(domain.writes)
