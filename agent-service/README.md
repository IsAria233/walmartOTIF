# Agent service

`app.investigation` builds a LangGraph workflow for one Fine Record and its PO
line. The graph checks scope, plans evidence reads, validates a structured
Finding, invokes Domain policy evaluation, and pauses for approval. A resume
signal prompts a fresh read of the same Outcome's approval status in Domain.

The graph factory takes an `InvestigationDomain` adapter and a `find_cause`
callback. SCRUM-27 tests use `SEED-02` with simulated Domain responses. SCRUM-28
will connect evidence reads to the Domain API.

## Run the tests

From `agent-service/`, install the service requirements and run the workflow tests.

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Set `AGENT_CHECKPOINT_TEST_DSN` to a disposable PostgreSQL database to also
exercise persistence. Use a Python PostgreSQL URI beginning with `postgresql://`.
The test starts one process to pause the run, then starts a second process to
resume it using the same `thread_id`. It checks that the Outcome is reused.

`open_investigation_graph` opens the PostgreSQL checkpointer and initializes its
tables. Use `config={"configurable": {"thread_id": run_id}}` for both start and
resume. Call `graph.invoke(Command(resume=True), config, durability="sync")`
after an approval notification. Domain remains the source of the approval result.
