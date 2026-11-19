"""Agent service: runs the LangGraph investigator for one investigation case."""
from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.domain_client import DomainClient, DomainError
from app.graph import anthropic_llm, investigate

app = FastAPI(title="agent-service")

# Finished runs, kept in memory for the POC. A restart loses them; the finding
# itself is stored in domain-service.
RUNS: dict[str, dict] = {}


class InvestigationRequest(BaseModel):
    case_id: str


@lru_cache
def _domain() -> DomainClient:
    return DomainClient()


@lru_cache
def _llm():
    return anthropic_llm()


@app.get("/health")
def health():
    return {"service": "agent-service", "status": "ok"}


@app.post("/investigations", status_code=201)
def start_investigation(request: InvestigationRequest):
    """Investigate one case and store the finding. Runs to completion before returning."""
    try:
        result = investigate(request.case_id, _domain(), _llm())
    except DomainError as exc:
        status = exc.status_code if exc.status_code in (404, 409) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    RUNS[result["run_id"]] = result
    return result


@app.get("/investigations/{run_id}")
def get_investigation(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")
    return RUNS[run_id]

# TODO (SCRUM-20): require the Auth Service JWT on these endpoints.
