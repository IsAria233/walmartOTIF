# Agent service

`app.investigation` builds a LangGraph workflow for one Fine Record and its PO
line. The graph checks scope, plans evidence reads, validates a structured
Finding, invokes Domain policy evaluation, and pauses for approval. A resume
signal prompts a fresh read of the same Outcome's approval status in Domain.

The graph factory takes an `InvestigationDomain` adapter and a `find_cause`
callback. Pass `DomainEvidenceReader` as `evidence_reader` to use real Domain
reads in the investigation node. Give the reader an `httpx.Client` configured
with the internal `DOMAIN_SERVICE_URL` as its base URL and a request timeout.

The reader fetches `/api/v1/investigation-contexts/{fine_record_id}` with the
current `case_id`. One request provides ASN lines, appointments, gate logs,
PO line versions, and receiving records. The reader returns the sources in the
graph's plan and preserves delivery IDs for gate and receiving evidence.
The record IDs are the UUIDs of the source records. The Domain client sends
the source and record ID with the Finding. Domain verifies each reference
against the case's PO line and creates the corresponding EvidenceRecord.

## Investigation API

Send the bearer token from Auth with each request.

| Method | Gateway path | Request |
| --- | --- | --- |
| POST | `/api/agent/investigations` | JSON with the Domain `case_id` |
| GET | `/api/agent/investigations/{run_id}` | No body |
| POST | `/api/agent/investigations/{run_id}/resume` | No body or an empty JSON object |

Start runs synchronously until the first pause or terminal state. Send a UUID
in the `Idempotency-Key` header and reuse it if the same start request needs
to be retried. The response includes the run ID, the status, and the finding
and outcome when available. Submit approvals through
`POST /api/domain/v1/outcomes/{outcome_id}/approvals` before calling resume.

A completed `needs_review` run includes a `handoff_id`. Domain exposes the
case in `GET /api/domain/v1/investigation-cases?status=handed_off`. Its detail
includes the reason, Agent run ID, evidence counts, missing sources, and any
saved Finding ID. Use the same `Idempotency-Key` to retry a start if the
handoff write is interrupted.

Compose sets `DOMAIN_SERVICE_URL` and `AGENT_CHECKPOINT_DSN`. From the project
root, run `docker compose exec domain-service alembic upgrade head` after
starting the services. Populate `distribution_centers.country_code` from the
DC data. Missing country data sends the run to `needs_review`.
Without a model key, starts return `503 model_not_configured`. Existing paused
runs can still be queried and resumed.

## Model findings

Use `open_finding_analyzer()` as a context manager and pass its analyzer to the
graph as `find_cause`. It loads `LLM_API_KEY` or `OPENAI_API_KEY` from the shell.
The default `LLM_MODEL` is `gpt-4.1-mini`. The Compose setup passes the project's
`.env` variables to the Agent service.

`DomainEvidenceReader.read_intake()` projects the MABD, transit days, and fine
snapshot used by the analyzer. The intake derives the U.S. DC scope flag
from the destination country. The model receives planned sources and selected fields.
LangGraph checks the cause and citations before submitting a Finding.

## Prompt injection guardrail

Agent checks the associated supplier dispute text, available attachment
metadata, and projected evidence for explicit instructions targeting the
workflow. These checks cover the text available in Domain. Attachment files
and linked URLs are outside this reader's scope.

A detected instruction goes to the existing Domain handoff queue with
`injection_detected: true` in the Agent response and a fixed review reason.
The model's structured output can also request the same handoff. SEED-03
supplies the regression input. The runtime follows section 6 of the OTIF
policy for the handoff.

## Observability

Agent emits structured logs with a deterministic trace ID based on `run_id`.
Use that ID to correlate start, retry, and approval resume with evidence
reads, model calls, Domain operations, and the handoff result. Events carry
status, duration, review or error codes, and model token counts when
available. Trace payloads contain operational metadata only.

Set both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` to also export
observations to Langfuse. The endpoint can be set with `LANGFUSE_BASE_URL`
or the existing `LANGFUSE_HOST` variable. Local logs work with blank keys.

## Run the tests

From `agent-service/`, install the service requirements and run the workflow tests.

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

To invoke OpenAI for the two synthetic seed cases, configure the API key in
the shell, then run the opt-in live test. This test makes two model requests
and uses a simulated Domain writer.

```bash
RUN_OPENAI_EVAL=1 python -m unittest discover -s tests -p 'test_model_finding.py' -v
```

Set `AGENT_CHECKPOINT_TEST_DSN` to a disposable PostgreSQL database to also
exercise persistence. Use a Python PostgreSQL URI beginning with `postgresql://`.
The test starts one process to pause the run, then starts a second process to
resume it using the same `thread_id`. It checks that the Outcome is reused.

`open_investigation_graph` opens the PostgreSQL checkpointer and initializes its
tables. Use `config={"configurable": {"thread_id": run_id}}` for both start and
resume. Call `graph.invoke(Command(resume=True), config, durability="sync")`
after an approval notification. Domain remains the source of the approval result.
