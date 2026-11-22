# OTIF frontend — POC setup and verification

React, Vite, React Router, JavaScript and native Fetch. Visual baseline:
`docs/frontend-design/Walmart_OTIF_UI_Demo_Business_First.html`; scope:
`docs/frontend-design/Walmart_OTIF_Frontend_Implementation_Plan_v1.1.md`.

## Development

Use Node 22.12+ (the production build uses Node 22):

```sh
cd frontend
npm ci
npm run dev
```

Vite serves port 5173 and proxies `/api` to the existing gateway on localhost:8080.
Start backend services using the repository's existing Compose setup and configure
backend secrets per the root/Auth documentation. No secrets belong in Vite variables.

```sh
npm run lint
npm test
npm run build
```

Vitest, jsdom and Testing Library exercise rendered routes and native Fetch boundaries.
There were no pre-existing frontend regression tests. These tests do not claim live
backend integration or browser acceptance, which are separate Phase 5 checks.

## Routes and permissions

- `/login`: real username/password login; no prefilled credentials or role selector.
- `/` redirects to `/cases`.
- `/cases`: investigation queue with server filters, sorting, refresh and pagination.
- `/fines`: paginated Fine Records list.
- `/fines/:fineId`: fine detail, related disputes and investigation links.
- `/cases/:caseId`: Case Workspace with Agent start/read, Findings, evidence,
  persisted Evaluations/Outcomes and Associate/Manager decisions.
- `/manager-review`: Manager-only candidate review view using existing APIs.
- `/forbidden`: access-denied destination; unmatched authenticated routes show not-found.

All three verified backend roles (`dispute_associate`, `compliance_manager`, `admin`)
can access the workspace and invoke Agent start/read. A shared role guard redirects denied roles to
`/forbidden`; navigation uses the same backend role vocabulary. No new permissions
or admin-only functionality are introduced. Approval controls follow
Domain's stage permissions (associates and managers for associate stage; managers
only for manager stage; admins cannot approve).

## Authentication and API contract

`POST /api/auth/login` receives `{username,password}` and returns a bearer access
token. `GET /api/auth/me` verifies the identity before any workspace is rendered.
The server-verified identity must include a UUID `user_id` and supported `role`.
Tokens are memory-only: reload requires sign-in again. Logout clears local state;
there is no server logout or refresh endpoint. The expiry timer is based on the
JWT `exp` solely for UI invalidation; JWT claims are not used to grant permissions.
401 clears the session; 403 preserves it and reports denied access. Login and
identity errors keep the workspace hidden. Passwords are cleared after submission.

`src/api/client.js` is the single Fetch boundary, normalizing Auth/Agent `detail`
and Domain `error` responses. `src/api/auth.js` is the only service-specific module
needed for authentication. `src/api/domain.js` defines the Phase 2 read paths and
pagination contract; `src/api/agent.js` defines Agent start and recovery metadata.

## Docker / Nginx

From the repository root:

```sh
docker compose --profile frontend up --build
```

The existing Compose frontend profile exposes port 3000. A Node build stage runs
`npm ci` and creates static assets; Nginx serves them with SPA deep-link fallback.
`/api/` preserves its URI when proxying to `gateway:80`, including Authorization.
Both development and production use same-origin browser requests, with no new
CORS configuration. Existing backend and Compose files are unchanged.

## Phase 2 read contracts

All reads use the existing centralized client and bearer token:

- `GET /api/domain/v1/investigation-cases`: `status`, `origin` (the `source`
  alias is accepted in queue URLs), `fine_record_id`, `supplier_id`,
  `created_from`, `created_to`, `page`, `page_size`, `sort_by`, `sort_order`.
  Sort fields are only `created_at`, `status`, and `origin`; backend Case ID
  ordering breaks ties. Date inputs are local time, converted to aware ISO
  timestamps. Filter application and sorting reset the page to 1.
- `GET /api/domain/v1/fine-records`: `page`, `page_size` only.
- `GET /api/domain/v1/fine-records/{id}`: persisted fine fields.
- `GET /api/domain/v1/fine-records/{id}/disputes`: independently paginated
  related dispute records. Amounts shown here cover the entire dispute,
  which can include more than one fine.
- Related investigations reuse the queue endpoint filtered by Fine Record ID.

Lists consume `{items,page,page_size,total,total_pages}`. Queue response columns
are restricted to Case ID, Fine Record ID, origin, creation timestamp and status.
No supplier-name enrichment, unsupported fine search, financial aggregation,
Agent actions, dispute writes or investigation-context calls are added.

Queue filters/sorting/pages and fine-list pages are URL-backed for back/forward
navigation. Each read uses AbortController and a completion guard; request keys
hide previous data immediately during navigation or refresh. A failed related
section can be retried independently without hiding fine details.

Phase 2 verification adds DTO, filtering, pagination, sort, navigation, loading,
empty/error/retry, 401/403 and stale-response tests. Live backend integration
remains unverified unless explicitly reported after running against real services.

## Phase 3 — Case Workspace and Agent

Read contracts verified against the current backend source:

- `GET /api/domain/v1/investigation-cases/{case_id}` returns Case fields and
  `handoff` only when currently handed off. The handoff includes reason,
  `occurred_at`, `agent_run_id`, and optional `handoff_details`.
- `GET /api/domain/v1/investigation-contexts/{fine_id}?case_id={case_id}` returns
  PO/line, supplier, DC, operational records and the selected Case context.
  Only the latest Finding has evidence snapshots/links in `evidence_context`.
- `GET /api/domain/v1/investigation-cases/{case_id}/findings?page=...&page_size=20`
  lists versions ascending. The context's `latest_finding.id`, not page 1's last
  item, identifies the current version. If context is unavailable, currentness
  is explicitly unconfirmed. `GET /api/domain/v1/findings/{id}` supplies facts,
  `source_records`, `evidence_ids`, confidence and ruled-out causes.
- `POST /api/agent/investigations` sends only `{case_id}` with a generated UUID
  `Idempotency-Key`. This is synchronous, not an asynchronous dispatch API.
  Eligible statuses: pending, investigating, revision_required, handed_off.
  The panel explains that this action may persist Findings/Evaluation/Outcome.
- `GET /api/agent/investigations/{run_id}` reads a known Run. Run fields come from
  `Investigator.read` (no explicit Pydantic response model). They include
  `run_id`, `case_id`, `status`, pause/unfinished flags, `model_steps`, `tool_log`,
  `trace_id`, raw `findings`, and Domain IDs. A mismatched Case is rejected.

Start metadata (key, completion flag and returned Run ID) is retained per user
and Case in sessionStorage with an in-memory fallback. No tokens or business
content are persisted there. Uncertain failures retain the same key, including
when a partial backend operation has changed the Case state. There is no automatic
POST retry. An explicit new investigation after a completed handoff/revision uses
a fresh key. Buttons lock during a request; navigating away does not cancel server
execution. Run ID is normally unavailable until the synchronous start returns.

The known Run form supports manually supplied IDs and explicit IDs from persisted
Findings/current handoff. It does not claim general Case-to-Run discovery. No
streaming, progress percentage, cancellation, resume or decision action is added.

Persisted Finding confidence uses `confidence_level` (or numeric `confidence`);
raw Agent findings instead use `cause`, string `confidence`, `verified_facts`,
`causes_checked`, `injected_instructions`. The UI keeps these representations
separate. Facts' citations open context records or supplied snapshots in a plain
text evidence inspector. Supplier disputes/attachments are labeled as claims.
Unavailable sources/older snapshots are explicit; no new evidence API, download
or upload is assumed. Snapshot availability must not be read as a complete audit
trail. The financial/history fields already included by context are not exposed
as Evaluation, Outcome or Approval controls in Phase 3.

Automated tests use deterministic contract-shaped fixtures, not live services.
Live authentication/model execution and Docker/Nginx runtime remain unverified.
This phase ends at the first consolidated UI/UX review; Phase 4 is not implemented.

Case refresh preserves the workspace and returned Agent result, including when
follow-up reads fail. Navigation to another Case still hides the previous record
immediately. Regression tests cover result preservation and the in-flight
duplicate-submit lock during refresh.

## Phase 4 — Evaluation and Approval (SCRUM-46 / SCRUM-47)

The Case Workspace's **Outcome & Approval** section separates persisted Domain
calculations from Agent assessments and human decisions. It shows Evaluation
version, exact Finding/Evaluation/Outcome IDs, policy version, cause, metric,
accountability, disposition and original/corrected/reversal amounts per line.
The browser never computes an official fine. Evaluation history has independent
pagination; Outcome history is ordered newest first. Only the first Outcome on
page 1 is eligible for decision controls; historical Outcomes are read-only.
Approval history loads every page before deriving a pending stage.

Gateway contracts used (in addition to Phase 3 Case/context/Finding reads):

- `GET /api/domain/v1/investigation-cases/{id}/evaluations`
- `GET /api/domain/v1/evaluations/{id}`
- `GET /api/domain/v1/investigation-cases/{id}/outcome` (singular path,
  paginated `{items: [{outcome, line_outcomes}], ...}` response)
- `GET /api/domain/v1/outcomes/{id}/approvals` returns approval records with
  nested append-only decisions, reviewer IDs, timestamps and comments.
- `POST /api/domain/v1/outcomes/{id}/approvals` sends
  `{line_outcome_id, stage, decision, comment}`. Identity comes from the JWT;
  neither user ID nor financial amounts are sent as decision inputs.
- `GET /api/agent/investigations/{run_id}` followed, only when appropriate, by
  `POST /api/agent/investigations/{run_id}/resume` with no request body.

Associates and Managers can decide Associate stages; only Managers can decide
Manager stages; Admin cannot decide. A pending Manager record and prior approved
Associate stage are required. The UI does not use a dollar threshold to authorize
an action: the Domain service's persisted stages are authoritative. The seeded
policy uses a strictly-greater-than threshold; no policy or threshold editing API
is exposed to the frontend.

A review confirmation is required and rejects need a nonblank reason. Before a
write, the client re-reads Case, latest Outcome and all approval pages to reject
stale/finalized decisions. It locks repeated submissions and validates the response
against the expected approval, actor and decision. A submitted write with an
uncertain result is never automatically retried. Recovery metadata, scoped by
user/Outcome/line, survives tab navigation using sessionStorage (memory fallback);
no comment, token or financial data is stored. **Check decision state** reads
history; if no completed record is confirmed, resubmission remains blocked.

After success, Domain reads are refreshed before the independent Agent operation.
The exact Line Outcome Finding supplies the Run ID. Run Case, Finding and Outcome
IDs must match and the Run must be paused for approval. A failed resume exposes
**Retry Agent resume**, which refreshes Domain and retries only Agent follow-up,
never the approval write. Missing Run IDs are reported, not guessed. Navigating
away before preflight finishes prevents the not-yet-submitted write.

The Manager navigation entry lists a paginated set of awaiting-approval candidate
Cases, then reads their current context to identify actual pending Manager lines.
Counts remain candidate-Case counts, not global pending-Manager counts. Decisions
are made in the Case Workspace after fresh stage checks.

Backend limitations / team follow-up:

- No repeated-DC-failure policy, queue or escalation API is implemented, so that
  part of SCRUM-47 is unsupported.
- No dedicated Manager-stage inbox or general Case-to-Run discovery endpoint.
- Domain locks pending stages, but its approval service does not explicitly enforce
  latest-Outcome ownership atomically. Frontend preflight and read-only history
  reduce stale writes but cannot eliminate a concurrent backend race.
- Approval POST has no idempotency key. Uncertain writes stay blocked until a
  completed decision can be confirmed; the UI cannot prove an in-flight write
  never committed.
- Available version/decision records are not a complete audit timeline.

Phase 4 tests use deterministic API fixtures and preserve all Phase 1–3 regressions.
No new dependencies, backend changes, real approval mutations or model calls are
needed for these tests. Live Phase 4 approval/resume integration is not claimed;
full-stack and final acceptance verification remain Phase 5 work.

## Phase 5 — Integration and final acceptance

### Required environment configuration (names only)

Compose loads the root `.env`. Keep it ignored and never put secrets in Vite:

| Names | Purpose |
| --- | --- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | PostgreSQL and Compose-generated service connections |
| `JWT_SECRET`, `AUTH_DEMO_PASSWORD_HASH` | Shared token verification and seeded-account login |
| `DATABASE_URL`, `DOMAIN_SERVICE_URL`, `AGENT_CHECKPOINT_DSN` | Supplied by Compose; set explicitly for non-Compose services |
| `ANTHROPIC_API_KEY` | Required only for new external-model investigations |
| `AGENT_MODEL`, `AGENT_MAX_STEPS` | Optional Agent overrides; omit rather than setting an empty model |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | Optional tracing integration |

`LLM_API_KEY` is obsolete. No frontend secrets or additional frontend variables
are needed. Auth, Domain and Agent must share the configured signing key.

### Local development / normal production demo

From the repository root, configure `.env` according to `.env.example` and the
Auth README. Never overwrite an existing environment file. Start the existing
stack with `docker compose up -d --build`, then `cd frontend && npm ci && npm run dev`.
The required services are PostgreSQL, Gateway, Auth, Domain and Agent. Vite uses
port 5173 with the existing Gateway on 8080. For Nginx production assets use
`docker compose --profile frontend up -d --build`; the frontend is on port 3000.
The Domain image applies existing migrations on startup.

Only load demo seeds into a designated development database when needed; the
existing loader skips already-loaded fine records. Never use reset scripts or
remove volumes to prepare a shared environment for testing.

Seeded usernames are `demo_associate`, `demo_manager`, and `demo_admin`. Use the
private password associated with `AUTH_DEMO_PASSWORD_HASH`; it is not published
in this README. The three accounts share the configured demo password. A browser
reload requires sign-in because access tokens are memory-only.

Useful paths: `/login`, `/cases`, `/fines`, `/fines/:fineId`, `/cases/:caseId`, and
Manager-only `/manager-review`. Normal flow: queue/fine -> Case -> Findings and
Evidence -> Outcome & Approval -> confirmed human decision -> separate Agent
resume. A new Agent investigation can incur model costs; do not start one merely
to inspect the UI.

### Isolated verification arrangement

`frontend/compose.verify.yml` supplements, and does not modify, root Compose. Use
only project **otif-frontend-verify** with separate test credentials. Its named
volume and network are separate from the normal development stack. The Gateway
is bound to localhost:18080 and the production Nginx frontend to localhost:13000.
External-model and tracing integrations are explicitly disabled. The override
requires Docker Compose support for `!override`.

Commands used for this verification (from repository root):

```sh
docker compose --env-file /tmp/otif-frontend-verify.env \
  -p otif-frontend-verify -f docker-compose.yml \
  -f frontend/compose.verify.yml --profile frontend build frontend

docker compose --env-file /tmp/otif-frontend-verify.env \
  -p otif-frontend-verify -f docker-compose.yml \
  -f frontend/compose.verify.yml --profile frontend up -d --no-build

python3 frontend/scripts/integration_smoke.py \
  --credentials-file /tmp/otif-frontend-verify-login.json \
  --compose-env /tmp/otif-frontend-verify.env \
  --allow-disposable-mutations --report /tmp/otif-phase5-integration.json
```

The private environment and login files are local-only, mode 0600, and are not
committed. Prepare matching test credentials using the Auth README's Argon2 hash
instructions if those temporary files are unavailable. The isolated database must
be named `otif_verify`, as checked by the fixture guard. Normal backend images
must already be built using the root Compose configuration. Load the existing
seed JSON only into this isolated environment before running mutation checks.

Mutation mode requires fresh pending seed Cases and refuses a used dataset;
it never resets records. Repeated verification against existing records can use
the same smoke command **without** `--allow-disposable-mutations` and `--compose-env`.
For a new full mutation run, prepare a fresh isolated database/volume deliberately;
do not reset the shared development database. Verification fixtures remain running
for acceptance review, and the normal development environment remains untouched.

`prepare_agent_fixture.py` executes a clearly labeled **SCRIPTED** local model
function through the real Investigator graph, real Domain REST workflows, and
normal PostgreSQL checkpoints. It creates disposable approval prerequisites and
handoffs; it is not evidence of external-model reasoning quality. It refuses the
normal database and enabled external credentials. It performs no direct business
DB edits. All resulting Findings label themselves as scripted integration fixtures.

### Executed results — 2026-11-22

- Frontend: ESLint, all 90 tests, production build and whitespace checks passed.
- Docker: frontend image built from the lockfile with Node 22; production Nginx
  and Gateway `nginx -t` passed; actual SPA deep links and API proxy worked.
- Isolated real HTTP suite: 61 checks passed, including all three role logins,
  `/me`, invalid-token rejection, filters, sort/pagination, fine detail/disputes,
  Finding citations, Evaluation/Outcome relations, Associate approve/reject,
  Manager approve/reject, stage/role enforcement, duplicate conflicts, persisted
  graph pause/resume and recorded handoff. Subsequent read-only rerun: 29 passed.
- Browser against production Nginx: protected deep-link login, logout, reload,
  Admin forbidden route, Manager navigation, required rejection comment, real
  Associate rejection + automatic resume, real Associate approval -> Manager
  stage, Manager candidate identification, and openable gate-log citation passed.
- Isolated Agent outage: four checks passed. A real resume request encountered
  network timeout/unavailability while Agent was stopped; after restart the same
  persisted Run resumed and approval history remained unchanged. The shared
  development database retained its original five pending Cases.

Live external-model investigation is **BLOCKED** without credentials and separate
cost authorization. Running-state UX, duplicate-click suppression, and uncertain
write/resume coordination have deterministic component coverage. The real resume
checks used scripted graph prerequisites; no paid model call was made.

### Jira acceptance and known limitations

| Jira | Result | Scope of evidence / gap |
| --- | --- | --- |
| SCRUM-43 | Verified | React/Router, production Docker/Nginx, gateway JWT forwarding, role guards |
| SCRUM-44 | Verified | Real three-role login, protected routes, logout/reload, forbidden state |
| SCRUM-45 | Partially verified | Real queue/status/read and idempotent fixture replay; new external-model execution blocked |
| SCRUM-46 | Verified for implemented POC | Real persisted Findings/citations, evaluations and Associate decisions; browser rejection reason required |
| SCRUM-47 | Partially verified | Real Manager stage/decisions; repeated DC failure escalation unsupported |

The rejection reason is enforced by the frontend; the current backend schema still
accepts an optional comment. Backend policy validation of mandatory rejection
comments is a team follow-up. No repeated-DC-failure policy or API was introduced.
Other known limitations remain: no complete audit timeline or dedicated Manager
inbox, latest-Outcome preflight cannot replace atomic backend validation, and
approval writes have no idempotency contract. Uncertain writes are not retried.

Final manual acceptance can use the running production fixture UI at
`http://127.0.0.1:13000`. The local private login file identifies the test login;
use its same private password for the other seeded roles. Findings there are
scripted fixtures, not external Agent reasoning. Read-only review can inspect
pending Associate/Manager stages, cited records, historical versions, handoffs and
completed decisions without affecting the normal development database.
