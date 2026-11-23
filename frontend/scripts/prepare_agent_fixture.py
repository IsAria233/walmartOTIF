"""Create a no-cost paused/handoff Run using the real graph in an isolated stack.

This is a SCRIPTED integration prerequisite, not external-model verification.
Run inside the isolated agent-service container with model/tracing keys disabled.
All business writes go through existing Domain APIs. Checkpoints use LangGraph's
normal Postgres saver. Refuses the shared development database.
"""
import argparse
import json
import os
import sys
import uuid
from types import SimpleNamespace

sys.path.insert(0, os.getcwd())
from psycopg import connect
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres import PostgresSaver
from app.domain_client import DomainClient
from app.graph import Investigator

parser = argparse.ArgumentParser()
parser.add_argument('--case', required=True)
parser.add_argument('--cause', choices=['C1', 'C2', 'C3', 'C4', 'C5', 'HANDOFF'], required=True)
parser.add_argument('--key', required=True)
args = parser.parse_args()
dsn = os.environ.get('AGENT_CHECKPOINT_DSN', '')
if not dsn.endswith('/otif_verify') or os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('LANGFUSE_PUBLIC_KEY'):
    raise SystemExit('Fixture requires isolated otif_verify database and disabled external integrations')
domain = DomainClient()
case = domain.get_case(args.case)
context = domain.get_context(case['fine_record_id'])
gate = context['deliveries'][0]['gate_logs'][0]
metric = context['fine_record']['metric']
causes = ['C1', 'C2'] if metric == 'on_time' else ['C3', 'C4', 'C5']

def scripted_llm(_system, _tools, _messages):
    findings = {
        'summary': 'SCRIPTED integration fixture. No external model was called.',
        'verified_facts': [{'fact': 'Integration fixture cites an existing gate record.',
                            'source_records': [{'record_type': 'gate_log', 'record_id': gate['id']}]}],
        'causes_checked': [{'cause': cause, 'verdict': 'supported' if cause == args.cause else 'ruled_out',
                           'reason': 'Scripted test prerequisite, not model inference.'} for cause in causes],
        'cause': args.cause, 'confidence': 'high',
        'handoff_note': 'SCRIPTED handoff fixture for human review UI.' if args.cause == 'HANDOFF' else '',
        'injected_instructions': [],
    }
    return SimpleNamespace(stop_reason='tool_use', content=[
        {'type': 'tool_use', 'id': 'fixture-read', 'name': 'get_gate_log', 'input': {}},
        {'type': 'tool_use', 'id': 'fixture-submit', 'name': 'submit_findings', 'input': findings},
    ])

run_id = str(uuid.uuid5(uuid.UUID(args.case), args.key))
with connect(dsn, autocommit=True, prepare_threshold=0, row_factory=dict_row) as conn:
    saver = PostgresSaver(conn)
    saver.setup()
    result = Investigator(domain, scripted_llm, saver).start(args.case, run_id)
assert result['status'] in ('awaiting_approval', 'handed_off'), result['status']
print(json.dumps({'case_id': args.case, 'run_id': result['run_id'], 'key': args.key,
                  'status': result['status'], 'domain': result['domain'],
                  'paused_for_approval': result['paused_for_approval']}))
