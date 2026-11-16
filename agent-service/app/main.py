"""Agent service: LangGraph investigator, tools, guardrails, LangFuse tracing.

Graph (first draft): intake -> scope check (code) -> plan causes ->
investigate loop (read-only tools) -> structured findings ->
rules call (domain-service) -> route -> approval pause -> finalize.
"""
from fastapi import FastAPI

app = FastAPI(title="agent-service")


@app.get("/health")
def health():
    return {"service": "agent-service", "status": "ok"}


# TODO: POST /investigations -> start a run for a dispute or flagged PO line
# TODO: GET /investigations/{id} -> status, findings, evidence
# TODO: POST /investigations/{id}/resume -> continue after human approval
