"""Agent service: starts, reads and resumes LangGraph investigations of one case."""
from __future__ import annotations

import logging
import os
import threading
from contextlib import ExitStack, asynccontextmanager, contextmanager
from typing import Annotated, Literal
from uuid import UUID, uuid4, uuid5

import jwt
import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, ConfigDict, ValidationError

from app.domain_client import DomainClient, DomainError
from app.graph import Investigator, anthropic_llm

logger = logging.getLogger("uvicorn.error")

# Case statuses from which a new investigation may start.
READY_TO_INVESTIGATE = {"pending", "investigating", "revision_required", "handed_off"}


class Runtime:
    """What the endpoints need: the investigator, the domain client and a per-case lock."""

    def __init__(self, investigator: Investigator, domain: DomainClient, checkpoint_dsn: str | None):
        self.investigator, self.domain, self._dsn = investigator, domain, checkpoint_dsn
        self._local_locks: dict[UUID, threading.Lock] = {}
        self._guard = threading.Lock()

    @contextmanager
    def lock_case(self, case_id: UUID):
        """One request per case at a time, across service instances when Postgres is configured."""
        busy = HTTPException(409, "Another investigation request for this case is in progress")
        if self._dsn:
            lock_id = int.from_bytes(case_id.bytes[:8], byteorder="big", signed=True)
            # The advisory lock is released when this connection closes.
            with psycopg.connect(self._dsn, autocommit=True, connect_timeout=5) as conn:
                if not conn.execute("SELECT pg_try_advisory_lock(%s)", (lock_id,)).fetchone()[0]:
                    raise busy
                yield
            return
        with self._guard:
            lock = self._local_locks.setdefault(case_id, threading.Lock())
        if not lock.acquire(blocking=False):
            raise busy
        try:
            yield
        finally:
            lock.release()


@asynccontextmanager
async def lifespan(app: FastAPI):
    dsn = os.getenv("AGENT_CHECKPOINT_DSN")
    with ExitStack() as stack:
        if dsn:
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            pool = stack.enter_context(ConnectionPool(
                dsn, min_size=1, max_size=4, open=False, timeout=10,
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            ))
            pool.wait()
            checkpointer = PostgresSaver(pool)
            checkpointer.setup()
        else:
            logger.warning("AGENT_CHECKPOINT_DSN is not set: investigation runs are kept in memory only")
            checkpointer = InMemorySaver()
        domain = DomainClient()
        llm = anthropic_llm() if os.getenv("ANTHROPIC_API_KEY") else None
        app.state.runtime = Runtime(Investigator(domain, llm, checkpointer), domain, dsn)
        app.state.model_available = llm is not None
        yield


app = FastAPI(title="agent-service", lifespan=lifespan)
bearer = HTTPBearer(auto_error=False, bearerFormat="JWT")


class InternalUser(BaseModel):
    sub: UUID
    role: Literal["dispute_associate", "compliance_manager", "admin"]


def require_internal_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> InternalUser:
    """Any signed-in internal user may run and read investigations. Approving is domain-service's check."""
    unauthorized = HTTPException(401, "Invalid or expired bearer token", headers={"WWW-Authenticate": "Bearer"})
    if credentials is None:
        raise unauthorized
    key = os.getenv("JWT_SECRET", "")
    if len(key.encode("utf-8")) < 32:
        raise HTTPException(503, "JWT verification is not configured")
    try:
        claims = jwt.decode(credentials.credentials, key, algorithms=["HS256"],
                            options={"require": ["sub", "role", "exp"]})
        return InternalUser.model_validate(claims)
    except (jwt.InvalidTokenError, ValidationError) as exc:
        raise unauthorized from exc


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


Authenticated = Depends(require_internal_user)
RuntimeDep = Annotated[Runtime, Depends(get_runtime)]


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: UUID


@app.get("/health")
def health():
    return {"service": "agent-service", "status": "ok"}


@app.post("/investigations", status_code=201, dependencies=[Authenticated])
def start_investigation(
    payload: InvestigationRequest, request: Request, response: Response, runtime: RuntimeDep,
    idempotency_key: Annotated[UUID | None, Header()] = None,
):
    """Investigate one case until it is handed off or waits for approval.

    With an Idempotency-Key header, repeating the request returns the same run
    (200) and continues it if an earlier attempt failed part-way.
    """
    case_id = payload.case_id
    run_id = str(uuid5(case_id, str(idempotency_key)) if idempotency_key else uuid4())
    with runtime.lock_case(case_id):
        if runtime.investigator.read(run_id) is not None:
            response.status_code = 200
            return runtime.investigator.start(str(case_id), run_id)
        if not request.app.state.model_available:
            raise HTTPException(503, "ANTHROPIC_API_KEY is not configured")
        case = runtime.domain.get_case(str(case_id))
        if case["status"] not in READY_TO_INVESTIGATE:
            raise HTTPException(409, f"Case is {case['status']}: not ready for a new investigation")
        return runtime.investigator.start(str(case_id), run_id)


@app.get("/investigations/{run_id}", dependencies=[Authenticated])
def get_investigation(run_id: UUID, runtime: RuntimeDep):
    run = runtime.investigator.read(str(run_id))
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


@app.post("/investigations/{run_id}/resume", dependencies=[Authenticated])
def resume_investigation(run_id: UUID, runtime: RuntimeDep):
    """Call after an approval decision: the run reads the result and finishes, or pauses for the next approver."""
    run = runtime.investigator.read(str(run_id))
    if run is None:
        raise HTTPException(404, "Run not found")
    with runtime.lock_case(UUID(run["case_id"])):
        return runtime.investigator.resume(str(run_id))


@app.exception_handler(DomainError)
def domain_error(_request: Request, exc: DomainError) -> JSONResponse:
    status = exc.status_code if exc.status_code in (404, 409) else 502
    return JSONResponse(status_code=status, content={"detail": str(exc)})


@app.exception_handler(psycopg.OperationalError)
def checkpoint_error(_request: Request, _exc: psycopg.OperationalError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "The checkpoint database is unavailable"})
