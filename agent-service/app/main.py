"""FastAPI service for the LangGraph OTIF investigator."""

import os
from contextlib import ExitStack, asynccontextmanager

import httpx
import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api import router
from .domain_investigation import DomainInvestigationClient, DomainRequestError
from .model_finding import open_finding_analyzer
from .observability import open_langfuse
from .runtime import open_runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    checkpoint_dsn = os.getenv("AGENT_CHECKPOINT_DSN")
    domain_url = os.getenv("DOMAIN_SERVICE_URL")
    with ExitStack() as stack:
        if checkpoint_dsn and domain_url:
            client = stack.enter_context(httpx.Client(base_url=domain_url, timeout=10))
            analyzer = None
            if os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"):
                analyzer = stack.enter_context(open_finding_analyzer())
            langfuse = stack.enter_context(open_langfuse())
            app.state.investigations = stack.enter_context(
                open_runtime(checkpoint_dsn, DomainInvestigationClient(client), analyzer, langfuse=langfuse),
            )
        try:
            yield
        finally:
            app.state.investigations = None


app = FastAPI(title="agent-service", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
def health():
    return {"service": "agent-service", "status": "ok"}


@app.exception_handler(DomainRequestError)
def domain_error(_request: Request, exc: DomainRequestError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": str(exc)})


@app.exception_handler(psycopg.OperationalError)
def checkpoint_error(_request: Request, _exc: psycopg.OperationalError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": {"code": "checkpoint_unavailable"}})
