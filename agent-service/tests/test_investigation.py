import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.investigation import Finding, PolicyReviewRequired, build_investigation_graph


AGENT_DIR = Path(__file__).resolve().parents[1]
SEED_CASE = AGENT_DIR.parent / "data-gen/seed_cases/trial/SEED-02_input.json"


def run_input(run_id):
    return {"run_id": run_id, "case_id": "SEED-02", "fine_record_id": "FINE-1002"}


class SeedDomain:
    def __init__(self):
        self.fixture = json.loads(SEED_CASE.read_text(encoding="utf-8"))
        self.writes = []
        self.approval_status = "pending_approval"
        self.evidence_reads = 0
        self.require_review = False

    def read_intake(self, case_id, fine_record_id):
        fine = self.fixture["fine_record"]
        assert (case_id, fine_record_id) == (self.fixture["case_id"], fine["fine_id"])
        po = self.fixture["po"]
        return {
            "po_line_id": f"{po['po_number']}:{po['line']}",
            "freight_terms": po["freight_terms"], "channel": po["channel"],
            "ships_to_us_dc": True, "metric": fine["metric"],
        }

    def read_evidence(self, case_id, fine_record_id, sources):
        assert (case_id, fine_record_id) == (self.fixture["case_id"], self.fixture["fine_record"]["fine_id"])
        self.evidence_reads += 1
        rows = {
            "asn": [self.fixture["asn"]] if self.fixture.get("asn") else [],
            "appointment_history": self.fixture["appointment_history"],
            "gate_log": self.fixture["gate_log"],
        }
        id_field = {"asn": "asn_id", "appointment_history": "event_id", "gate_log": "gate_id"}
        return {
            source: [{"record_id": row[id_field[source]], "facts": row} for row in rows[source]]
            for source in sources
        }

    def submit_finding(self, case_id, run_id, finding, evidence):
        assert finding["cause_code"] == "C2"
        self.writes.append("finding")
        return "finding-02"

    def evaluate(self, case_id, finding_id):
        self.writes.append("evaluation")
        if self.require_review:
            raise PolicyReviewRequired("Finding conflicts with the original fine accountability")
        return "evaluation-02"

    def create_outcome(self, case_id, evaluation_id):
        self.writes.append("outcome")
        return "outcome-02"

    def read_approval_status(self, case_id, outcome_id):
        assert (case_id, outcome_id) == ("SEED-02", "outcome-02")
        return self.approval_status


def seed_finding(case, plan, evidence):
    event = next(row for row in evidence["appointment_history"] if row["facts"]["by"] == "DC")
    return Finding(
        cause_code="C2",
        summary="The DC rescheduled the delivery appointment",
        confidence=1,
        facts=[{
            "fact_key": "dc_rescheduled", "fact_value": event["facts"]["slot"],
            "evidence_ids": [event["record_id"]],
        }],
    )


class InvestigationTests(unittest.TestCase):
    def start(self, domain, find_cause=seed_finding):
        graph = build_investigation_graph(
            domain=domain, find_cause=find_cause, checkpointer=InMemorySaver(),
        )
        run_id = str(uuid4())
        config = {"configurable": {"thread_id": run_id}}
        return graph, config, graph.invoke(run_input(run_id), config)

    def test_seed_case_pauses_at_both_approval_stages(self):
        domain = SeedDomain()
        graph, config, result = self.start(domain)
        self.assertEqual(result["finding"]["cause_code"], "C2")
        self.assertEqual(result["finding"]["facts"][0]["evidence_ids"], ["APT-9002-2"])
        self.assertEqual(result["__interrupt__"][0].value["status"], "pending_approval")

        domain.approval_status = "pending_manager_approval"
        result = graph.invoke(Command(resume={"status": "approved"}), config)
        self.assertEqual(result["__interrupt__"][0].value["status"], "pending_manager_approval")

        domain.approval_status = "approved"
        result = graph.invoke(Command(resume=True), config)
        self.assertEqual(result["result"]["status"], "approved")
        self.assertEqual(domain.writes, ["finding", "evaluation", "outcome"])

    def test_out_of_scope_skips_evidence(self):
        domain = SeedDomain()
        domain.fixture["po"]["freight_terms"] = "collect"
        _, _, result = self.start(domain)
        self.assertEqual(result["result"]["status"], "out_of_scope")
        self.assertEqual(domain.evidence_reads, 0)
        self.assertFalse(domain.writes)

    def test_missing_asn_hands_off_before_writes(self):
        domain = SeedDomain()
        del domain.fixture["asn"]
        _, _, result = self.start(domain)
        self.assertEqual(result["result"]["status"], "needs_review")
        self.assertIn("asn", result["result"]["handoff_reason"])
        self.assertFalse(domain.writes)

    def test_unknown_citation_hands_off_before_writes(self):
        def unsupported_finding(case, plan, evidence):
            finding = seed_finding(case, plan, evidence)
            finding.facts[0].evidence_ids = ["UNKNOWN-RECORD"]
            return finding

        domain = SeedDomain()
        _, _, result = self.start(domain, unsupported_finding)
        self.assertEqual(result["result"]["status"], "needs_review")
        self.assertFalse(domain.writes)

    def test_policy_conflict_hands_off_without_outcome(self):
        domain = SeedDomain()
        domain.require_review = True
        _, _, result = self.start(domain)
        self.assertEqual(result["result"]["status"], "needs_review")
        self.assertEqual(domain.writes, ["finding", "evaluation"])
        self.assertNotIn("outcome_id", result["result"])

    @unittest.skipUnless(os.getenv("AGENT_CHECKPOINT_TEST_DSN"), "PostgreSQL test DSN is not configured")
    def test_postgres_checkpoint_survives_process_restart(self):
        run_id = str(uuid4())

        def run_phase(phase):
            completed = subprocess.run(
                [sys.executable, "-c", CHECKPOINT_PROCESS, run_id, phase],
                cwd=AGENT_DIR, capture_output=True, text=True, timeout=30, check=True,
            )
            return json.loads(completed.stdout)

        paused = run_phase("start")
        self.assertEqual(paused["status"], "pending_approval")
        self.assertEqual(paused["writes"], ["finding", "evaluation", "outcome"])
        resumed = run_phase("resume")
        self.assertEqual(resumed["status"], "approved")
        self.assertEqual(resumed["outcome_id"], paused["outcome_id"])
        self.assertEqual(resumed["writes"], [])


CHECKPOINT_PROCESS = """
import json
import os
import sys

from langgraph.types import Command
from app.investigation import open_investigation_graph

sys.path.insert(0, 'tests')
from test_investigation import SeedDomain, run_input, seed_finding

run_id, phase = sys.argv[1:]
domain = SeedDomain()
if phase == 'resume':
    domain.approval_status = 'approved'
config = {'configurable': {'thread_id': run_id}}
with open_investigation_graph(os.environ['AGENT_CHECKPOINT_TEST_DSN'], domain=domain, find_cause=seed_finding) as graph:
    initial = run_input(run_id) if phase == 'start' else Command(resume=True)
    result = graph.invoke(initial, config, durability='sync')
print(json.dumps({'status': result['status'], 'outcome_id': result['outcome_id'], 'writes': domain.writes}))
"""
