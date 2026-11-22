"""Real HTTP smoke checks against isolated Nginx/Gateway/services.

Default: read-only. Mutation mode requires test credentials, isolated Compose
configuration, and fresh seed Cases. Never calls an external model. No secrets
are printed. Scripted graph fixtures are explicitly distinct from model execution.
"""
import argparse
import json
import subprocess
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://127.0.0.1:13000')
parser.add_argument('--credentials-file', required=True)
parser.add_argument('--compose-env')
parser.add_argument('--allow-disposable-mutations', action='store_true')
parser.add_argument('--report', required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
credentials = json.loads(Path(args.credentials_file).read_text())
checks = []

def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)
    print('PASS:', name, flush=True)

def call(path, token=None, body=None, method=None, expected=200, headers=None):
    request_headers = {'Accept': 'application/json', **(headers or {})}
    if token:
        request_headers['Authorization'] = 'Bearer ' + token
    if body is not None:
        request_headers['Content-Type'] = 'application/json'
    request = Request(args.base_url + path, data=json.dumps(body).encode() if body is not None else None,
                      headers=request_headers, method=method)
    try:
        response = urlopen(request, timeout=30)
    except HTTPError as error:
        response = error
    # Never print response content on authentication failures.
    status = response.code
    content = response.read().decode()
    if status != expected:
        raise AssertionError(f'{method or "GET"} {path}: expected {expected}, got {status}')
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content

D = '/api/domain/v1'
for path in ['/health', '/api/auth/health', '/api/domain/health', '/api/agent/health']:
    check('Nginx/Gateway health ' + path, bool(call(path)))
for path in ['/login', '/cases', '/fines', '/manager-review', '/cases/' + str(uuid.uuid4())]:
    check('production SPA deep link ' + path, 'id="root"' in call(path))
tokens = {}
for username, role in [('demo_associate', 'dispute_associate'), ('demo_manager', 'compliance_manager'), ('demo_admin', 'admin')]:
    token = call('/api/auth/login', body={'username': username, 'password': credentials['password']})['access_token']
    tokens[role] = token
    check('real login + /me ' + role, call('/api/auth/me', token)['role'] == role)
call('/api/auth/me', expected=401)
call('/api/auth/me', token='invalid', expected=401)
check('Auth rejects missing and invalid bearer', True)
associate, manager, admin = (tokens[key] for key in ['dispute_associate', 'compliance_manager', 'admin'])
fines = call(D + '/fine-records?page_size=100', associate)
cases = call(D + '/investigation-cases?page_size=100', associate)
check('real seeded queue and fines', fines['total'] >= 5 and cases['total'] >= 5)
fine_map = {item['id']: item for item in fines['items']}
case_map = {fine_map[item['fine_record_id']]['external_fine_id']: item for item in cases['items']}
record = case_map['FINE-1002']
context = call(D + '/investigation-contexts/' + record['fine_record_id'] + '?case_id=' + record['id'], associate)
for query in ['status=' + record['status'], 'origin=' + record['origin'], 'source=' + record['origin'],
              'fine_record_id=' + record['fine_record_id'], 'supplier_id=' + context['supplier']['id'],
              'created_from=2020-01-01T00%3A00%3A00Z', 'created_to=2100-01-01T00%3A00%3A00Z']:
    result = call(D + '/investigation-cases?' + query, associate)
    check('queue filter ' + query.split('=')[0], any(item['id'] == record['id'] for item in result['items']))
for field in ['created_at', 'status', 'origin']:
    result = call(D + '/investigation-cases?sort_by=' + field + '&sort_order=asc', associate)
    check('server sorting ' + field, [item[field] for item in result['items']] == sorted(item[field] for item in result['items']))
first = call(D + '/investigation-cases?page_size=2&page=1', associate)
second = call(D + '/investigation-cases?page_size=2&page=2', associate)
check('queue totals and pagination', first['total'] == cases['total'] and first['total_pages'] == (cases['total'] + 1) // 2 and not ({x['id'] for x in first['items']} & {x['id'] for x in second['items']}))
check('fine detail', call(D + '/fine-records/' + record['fine_record_id'], associate)['id'] == record['fine_record_id'])
check('related disputes', call(D + '/fine-records/' + record['fine_record_id'] + '/disputes', associate)['total'] >= 1)
check('Case context and PO', bool(context['purchase_order']['po_number']) and context['case_context'][0]['case']['id'] == record['id'])
call(D + '/fine-records/not-a-uuid', associate, expected=422)
call(D + '/fine-records/' + str(uuid.uuid4()), associate, expected=404)
check('real validation and not-found responses', True)
report = {'checks': checks, 'cases': case_map, 'mode': 'read-only'}
if args.allow_disposable_mutations:
    if args.base_url != 'http://127.0.0.1:13000' or not args.compose_env:
        raise SystemExit('Mutation mode requires isolated localhost:13000 and explicit Compose test env')
    compose = ['docker', 'compose', '--env-file', str(Path(args.compose_env).resolve()), '-p', 'otif-frontend-verify',
               '-f', str(root / 'docker-compose.yml'), '-f', str(root / 'frontend/compose.verify.yml')]
    # Verify the actual DB destination, without revealing DSNs or credentials.
    isolated = subprocess.check_output(compose + ['exec', '-T', 'agent-service', 'python', '-c',
        "import os;print(os.getenv('AGENT_CHECKPOINT_DSN','').endswith('/otif_verify') and not os.getenv('ANTHROPIC_API_KEY'))"], text=True).strip()
    if isolated != 'True' or cases['total'] != 5 or any(item['status'] != 'pending' for item in cases['items']):
        raise SystemExit('Mutation mode requires a fresh isolated seed environment')
    call('/api/agent/investigations', associate, {'case_id': record['id']}, expected=503,
         headers={'Idempotency-Key': str(uuid.uuid4())})
    check('new external-model run blocked without credentials', True)
    fixture_text = (root / 'frontend/scripts/prepare_agent_fixture.py').read_text()
    fixtures = {}

    def fixture(name, cause):
        case_id = case_map[name]['id']
        output = subprocess.check_output(compose + ['exec', '-T', 'agent-service', 'python', '-', '--case', case_id,
            '--cause', cause, '--key', str(uuid.uuid4())], input=fixture_text, text=True)
        value = json.loads(output)
        fixtures[name] = value
        check('SCRIPTED graph fixture ' + name, value['status'] in ['awaiting_approval', 'handed_off'])
        if value['status'] == 'awaiting_approval':
            check('real paused checkpoint read ' + name, call('/api/agent/investigations/' + value['run_id'], associate)['paused_for_approval'])
            replay = call('/api/agent/investigations', associate, {'case_id': case_id},
                          headers={'Idempotency-Key': value['key']})
            check('idempotent known-run replay ' + name, replay['run_id'] == value['run_id'])
        return value

    def outcome(value):
        rows = call(D + '/investigation-cases/' + value['case_id'] + '/outcome', associate)['items']
        return next(item for item in rows if item['outcome']['id'] == value['domain']['outcome_id'])

    def decide(value, stage, decision, token, expected=201):
        item = outcome(value)
        return call(D + '/outcomes/' + item['outcome']['id'] + '/approvals', token,
                    {'line_outcome_id': item['line_outcomes'][0]['id'], 'stage': stage, 'decision': decision,
                     'comment': 'Disposable Phase 5 integration check'}, expected=expected)

    def resume(value, expected_status):
        result = call('/api/agent/investigations/' + value['run_id'] + '/resume', associate, method='POST')
        check('real resume ' + expected_status, result['status'] == expected_status)

    simple = fixture('FINE-1001', 'C1')
    evaluated = call(D + '/evaluations/' + simple['domain']['evaluation_id'], associate)
    finding = call(D + '/findings/' + simple['domain']['finding_id'], associate)
    check('persisted Evaluation/Finding relation', evaluated['finding_id'] == finding['id'])
    ctx = call(D + '/investigation-contexts/' + case_map['FINE-1001']['fine_record_id'] + '?case_id=' + simple['case_id'], associate)
    check('real Finding citations resolve to context', finding['facts'][0]['source_records'][0]['record_id'] == ctx['deliveries'][0]['gate_logs'][0]['id'])
    decide(simple, 'associate', 'approved', None, 401)
    decide(simple, 'associate', 'approved', admin, 403)
    decide(simple, 'associate', 'approved', associate)
    decide(simple, 'associate', 'approved', associate, 409)
    check('Associate authorization, approval and duplicate conflict', True)
    # Real missing-Run failure leaves the already-recorded decision untouched.
    call('/api/agent/investigations/' + str(uuid.uuid4()) + '/resume', associate, method='POST', expected=404)
    resume(simple, 'approved')
    history = call(D + '/outcomes/' + simple['domain']['outcome_id'] + '/approvals', associate)
    check('resume recovery without duplicate approval', sum(len(item['decisions']) for item in history['items']) == 1)
    rejected = fixture('FINE-1003', 'C3')
    decide(rejected, 'associate', 'rejected', associate)
    resume(rejected, 'rejected')
    check('Associate rejection requires revision', call(D + '/investigation-cases/' + rejected['case_id'], associate)['status'] == 'revision_required')
    high = fixture('FINE-1002', 'C2')
    decide(high, 'manager', 'approved', manager, 409)
    decide(high, 'associate', 'approved', associate)
    check('Domain creates Manager stage for actual reversal', outcome(high)['outcome']['status'] == 'pending_manager_approval')
    resume(high, 'awaiting_approval')
    decide(high, 'manager', 'approved', associate, 403)
    decide(high, 'manager', 'approved', admin, 403)
    decide(high, 'manager', 'rejected', manager)
    resume(high, 'rejected')
    check('Manager rejection requires revision', call(D + '/investigation-cases/' + high['case_id'], associate)['status'] == 'revision_required')
    high = fixture('FINE-1002', 'C2')
    decide(high, 'associate', 'approved', associate)
    resume(high, 'awaiting_approval')
    decide(high, 'manager', 'approved', manager)
    resume(high, 'approved')
    check('Manager approval closes Case', call(D + '/investigation-cases/' + high['case_id'], associate)['status'] == 'closed')
    fixture('FINE-1004', 'C4')  # leave one pending line for browser inspection
    handed = fixture('FINE-1005', 'HANDOFF')
    check('recorded handoff detail', bool(call(D + '/investigation-cases/' + handed['case_id'], associate)['handoff']['reason']))
    report.update({'mode': 'disposable mutations + SCRIPTED no-cost graph fixtures', 'fixtures': fixtures})
report['passed_count'] = len(checks)
Path(args.report).write_text(json.dumps(report, indent=2))
print('Completed checks:', len(checks), 'No external model calls executed.')
