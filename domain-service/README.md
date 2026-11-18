# Domain Service API and workflow notes

## Local setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) using the
installer for your operating system. The repository pins Python 3.11 for this
service. Install that interpreter if needed, then create/synchronize the local
environment from this directory:

```sh
uv python install 3.11
uv sync --dev
```

Run the tests and start the API with:

```sh
uv run pytest -q
uv run uvicorn app.main:app --reload --port 8000
```

The project is an application, not an installable Python library; uv manages
its environment without building or installing a wheel. The root `.gitignore`
already excludes `.venv/`.

### PostgreSQL and Alembic

Set `DATABASE_URL` in the shell that runs the service or Alembic. Use a local
PostgreSQL role and database appropriate to your environment; do not commit
credentials:

```sh
export DATABASE_URL='postgresql+psycopg2://USER:PASSWORD@HOST:5432/DATABASE'
uv run alembic heads
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

Only run `alembic upgrade head` against a database intended for this service.
For migration or concurrency integration tests, use a disposable isolated
PostgreSQL database. The `test_postgres_*` fixtures require
`SCRUM15_TEST_DATABASE_URL` and refuse to run against a database other than the
configured SCRUM-15 test target; without that variable, those tests are skipped.
The regular test suite uses SQLite-backed fixtures and does not require a live
database.

## Ownership and service boundary

The Domain Service owns Fine Records, Disputes and Dispute Lines, Investigation
Cases, Findings and Evidence references, Evaluations, Outcomes, Approvals, and
the documented OTIF rules. Agent Run IDs and Auth user IDs are external UUID
references. There are no local Agent or User tables. Agent dispatch, Gateway
authentication/JWT verification, and agent orchestration are outside this
service. `POST /api/v1/investigation-cases` is intended for internal Domain
callers; this application currently has no internal-caller authorization
mechanism. Approval routes require the trusted Gateway to set
`request.state.authenticated_user_id`; until wired, they return 503.

## Route groups

All routes use `/api/v1`:

- Reference reads: suppliers, POs/lines/versions, ASNs, appointments,
  deliveries/gate logs, receiving records, and DC weather alerts.
- Fine and Dispute reads/writes: fine records and disputes. A Dispute submit
  accepts one to three lines and is handled in one caller-owned transaction.
- Investigation Cases: create/reuse, queue, detail, and lifecycle status.
- Findings and Evaluations: append-only versions, exact Finding reference.
- Outcomes and Approvals: aggregate Outcome with independently reviewable
  Line Outcomes and append-only Approval Decisions.
- Pre-invoice scan and read-only investigation context.

## Case lifecycle and version history

Statuses are `pending`, `investigating`, `findings_submitted`,
`awaiting_approval`, `handed_off`, `revision_required`, and `closed`. Allowed
transitions are enforced by `case_service`; each transition records a status
event including the optional reason. A partial unique index permits at most one
non-closed Case per Fine Record while retaining closed history. Creation and
reuse lock the Fine Record row; all creation paths call the shared helper.

Findings and Evaluations receive monotonically increasing per-Case versions
while locking the Case. The latest record is the highest version. Evaluations
retain the exact Finding ID and a complete JSON snapshot. Findings, facts,
Evidence snapshots/links, Evaluations, and Approval Decisions are guarded as
append-only in PostgreSQL. The old Case `dispute_line_id` remains during the
expand/backfill rollout; new code writes the `dispute_line_cases` association.

## Evaluator, Outcomes, and approval

The only currently documented policy source is [`../docs/otif_policy.md`](../docs/otif_policy.md),
POC policy v0.1. The migration seeds policy version `0.1` with its documented
3% fine rate and $500 manager threshold. The evaluator computes the amount from
Domain-owned Fine Record quantities, case cost, and supported accountability;
it does not classify C1–C5 or use Agent prose as financial authority. It
rejects unsupported accountability and handoff/injection findings. Missing or
conflicting facts therefore require product/policy work before broader
automated adjudication.
Policy v0.1 does not specify currency rounding. The evaluator refuses an amount
that is not already exact to cents instead of choosing an undocumented rule.

One Evaluation may have one aggregate Case Outcome. Each aggregate has one or
more Line Outcomes, each retaining the original/corrected/reversal amounts and
approval state. Associate approval is first. A reversal above the configured
policy threshold requires Manager approval. Decisions are appended, line
locked, and a rejection moves the Case to `revision_required`. Only when every
Line Outcome in the current aggregate is approved can the Case close.

## Write examples

Create or reuse an internal pre-invoice Case:

```http
POST /api/v1/investigation-cases
Content-Type: application/json

{"fine_record_id":"<uuid>","origin":"pre_invoice_scan"}
```

Submit a Dispute atomically:

```json
{
  "supplier_id":"<uuid>",
  "lines":[{"fine_record_id":"<uuid>","amount_disputed":"125.00"}],
  "attachments":[{"filename":"pod.pdf","fine_record_id":"<same-fine-record-uuid>"}]
}
```

Submit a Finding version:

```json
{
  "agent_run_id":"<uuid>","summary":"Review summary",
  "facts":[{"fact_key":"gate_check_in","fact_value":"2026-01-03T12:00:00Z","evidence_ids":[]}]
}
```

Evaluate an exact Finding, then create an Outcome:

```json
{"finding_id":"<finding-uuid>"}
```

```json
{"evaluation_id":"<evaluation-uuid>"}
```

Record a line-specific Associate decision (the authenticated user comes from
Gateway request state, never this body):

```json
{"line_outcome_id":"<line-outcome-uuid>","stage":"associate","decision":"approved","comment":"Reviewed"}
```

Run an idempotent scan:

```json
{"scan_id":"invoice-batch-2026-03-14","fine_record_ids":["<fine-uuid>"]}
```

## Migration history and behavior

Revision sequence: `0001_domain_schema` → `0002_review_revisions` →
`0003_case_attachment_consistency` → `0004_scrum15_domain_workflows`.
The new revision fails if legacy Case status is null/unsupported or duplicate
Active Cases exist; it does not silently close Cases. Only already-canonical
status values are accepted as-is. Scan rules without historical scan IDs use
the explicit sentinel `legacy-unknown`. The legacy direct Case/Dispute Line
column is retained; do not remove it until a separate contract migration is
reviewed. Existing Line Outcomes are migrated into a legacy-snapshot
Evaluation and one-line aggregate Outcome without recalculating their amounts.
Downgrade guards refuse to discard new Evaluation, scan, status-event, policy,
or Case association history. This revision adds seven Domain tables, for 32 total.
