"""Agent service: LangGraph investigator, tools, guardrails, LangFuse tracing.

The investigation graph and persistent checkpoint setup live in app.investigation.
"""
from fastapi import FastAPI

app = FastAPI(title="agent-service")


@app.get("/health")
def health():
    return {"service": "agent-service", "status": "ok"}


# TODO: POST /investigations -> start a run for a dispute or flagged PO line
# TODO: GET /investigations/{id} -> status, findings, evidence
# TODO: POST /investigations/{id}/resume -> continue after human approval
