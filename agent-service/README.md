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
The record IDs are the UUIDs of the source records. The Domain write adapter
must resolve these to EvidenceRecord UUIDs before submitting a Finding.

## Model findings

Use `open_finding_analyzer()` as a context manager and pass its analyzer to the
graph as `find_cause`. It loads `LLM_API_KEY` or `OPENAI_API_KEY` from the shell.
The default `LLM_MODEL` is `gpt-4.1-mini`. The Compose setup passes the project's
`.env` variables to the Agent service.

`DomainEvidenceReader.read_intake()` projects the MABD, transit days, and fine
snapshot used by the analyzer. The intake caller supplies the verified U.S. DC
scope flag. The model receives only planned sources and selected fields.
LangGraph checks the cause and citations before submitting a Finding.

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
