"""The HTTP entry points for starting, reading, and resuming an investigation."""

import os
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import UUID, uuid4, uuid5

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StateSnapshot
from pydantic import BaseModel, ConfigDict, ValidationError

from .domain_investigation import READY_TO_INVESTIGATE, DomainCase
from .investigation import Finding, InvestigationInput, PENDING_APPROVAL, RunStatus
from .observability import observe

if TYPE_CHECKING:
    from langfuse import Langfuse

router = APIRouter(prefix="/investigations", tags=["investigations"])
bearer = HTTPBearer(auto_error=False, bearerFormat="JWT")


class InternalUser(BaseModel):
    sub: UUID
    role: Literal["dispute_associate", "compliance_manager", "admin"]


def require_internal_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> InternalUser:
    unauthorized = HTTPException(401, "Invalid or expired bearer token", headers={"WWW-Authenticate": "Bearer"})
    if credentials is None:
        raise unauthorized
    key = os.getenv("JWT_SECRET", "")
    if len(key.encode("utf-8")) < 32:
        raise HTTPException(503, "JWT verification is not configured")
    try:
        claims = jwt.decode(credentials.credentials, key, algorithms=["HS256"], options={"require": ["sub", "role", "exp"]})
        return InternalUser.model_validate(claims)
    except (jwt.InvalidTokenError, ValidationError) as exc:
        raise unauthorized from exc


class StartInvestigation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: UUID


class ResumeInvestigation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvestigationResponse(BaseModel):
    run_id: UUID
    case_id: UUID
    fine_record_id: UUID
    status: RunStatus = "investigating"
    finding: Finding | None = None
    finding_id: UUID | None = None
    evaluation_id: UUID | None = None
    outcome_id: UUID | None = None
    handoff_reason: str | None = None
    handoff_id: UUID | None = None
    injection_detected: bool = False


@dataclass(frozen=True)
class InvestigationRuntime:
    graph: CompiledStateGraph
    get_case: Callable[[str], DomainCase]
    lock_case: Callable[[UUID], AbstractContextManager[None]]
    model_available: bool
    langfuse: "Langfuse | None" = None


def get_runtime(request: Request) -> InvestigationRuntime:
    runtime = getattr(request.app.state, "investigations", None)
    if runtime is None:
        raise HTTPException(503, detail={"code": "checkpoint_not_configured"})
    return runtime


Runtime = Annotated[InvestigationRuntime, Depends(get_runtime)]


def _config(run_id: UUID) -> dict[str, Any]:
    return {"configurable": {"thread_id": str(run_id)}}


def _read_run(snapshot: StateSnapshot) -> InvestigationResponse:
    if "run_id" not in snapshot.values:
        raise HTTPException(404, "Investigation run not found")
    return InvestigationResponse.model_validate(snapshot.values)


def _invoke_run(
    runtime: InvestigationRuntime, case_id: UUID, run_id: UUID, phase: str,
    value: InvestigationInput | Command | None,
) -> InvestigationResponse:
    config = _config(run_id)
    with observe(phase, as_type="agent", run_id=str(run_id), case_id=str(case_id), client=runtime.langfuse) as event:
        runtime.graph.invoke(value, config, durability="sync")
        snapshot = runtime.graph.get_state(config)
        run = _read_run(snapshot)
        event.workflow_status = run.status
        event.review_code = snapshot.values.get("review_code")
        return run


@router.post(
    "", response_model=InvestigationResponse, status_code=201,
    responses={200: {"model": InvestigationResponse, "description": "Existing run for this idempotency key"}},
    dependencies=[Depends(require_internal_user)],
)
def start_investigation(
    payload: StartInvestigation, response: Response, runtime: Runtime,
    idempotency_key: Annotated[UUID | None, Header()] = None,
) -> InvestigationResponse:
    case_id = payload.case_id
    run_id = uuid5(case_id, str(idempotency_key)) if idempotency_key else uuid4()
    config = _config(run_id)
    with runtime.lock_case(case_id):
        snapshot = runtime.graph.get_state(config)
        if "run_id" in snapshot.values:
            response.status_code = 200
            if snapshot.next and not snapshot.interrupts:
                return _invoke_run(runtime, case_id, run_id, "investigation.retry", None)
            return _read_run(snapshot)

        if not runtime.model_available:
            raise HTTPException(503, detail={"code": "model_not_configured"})
        case = runtime.get_case(str(case_id))
        if case.status not in READY_TO_INVESTIGATE:
            raise HTTPException(409, "Case is not ready for a new investigation")
        return _invoke_run(
            runtime, case_id, run_id, "investigation.start",
            {"run_id": str(run_id), "case_id": str(case_id), "fine_record_id": str(case.fine_record_id)},
        )


@router.get("/{run_id}", response_model=InvestigationResponse, dependencies=[Depends(require_internal_user)])
def read_investigation(run_id: UUID, runtime: Runtime) -> InvestigationResponse:
    return _read_run(runtime.graph.get_state(_config(run_id)))


@router.post("/{run_id}/resume", response_model=InvestigationResponse, dependencies=[Depends(require_internal_user)])
def resume_investigation(
    run_id: UUID, runtime: Runtime, _payload: ResumeInvestigation | None = None,
) -> InvestigationResponse:
    config = _config(run_id)
    case_id = _read_run(runtime.graph.get_state(config)).case_id
    with runtime.lock_case(case_id):
        snapshot = runtime.graph.get_state(config)
        run = _read_run(snapshot)
        if run.status in PENDING_APPROVAL and snapshot.next:
            command = Command(resume=True) if snapshot.interrupts else None
            return _invoke_run(runtime, case_id, run_id, "investigation.resume", command)
        if snapshot.next:
            raise HTTPException(409, "Investigation has not reached approval")
        return run
