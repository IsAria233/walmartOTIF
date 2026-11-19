"""Metadata-only tracing for one investigation across start and resume."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal

from langgraph.errors import GraphInterrupt

if TYPE_CHECKING:
    from langfuse import Langfuse

logger = logging.getLogger("uvicorn.error.agent")
ObservationType = Literal["agent", "chain", "generation", "tool"]


@dataclass
class Observation:
    workflow_status: str | None = None
    review_code: str | None = None
    usage: dict[str, int] | None = None


@dataclass(frozen=True)
class ActiveObservation:
    run_id: str
    case_id: str
    trace_id: str
    span: Any | None


current: ContextVar[ActiveObservation | None] = ContextVar("agent_observation", default=None)


@contextmanager
def open_langfuse() -> Iterator[Langfuse | None]:
    from langfuse import Langfuse

    public_key, secret_key = os.getenv("LANGFUSE_PUBLIC_KEY"), os.getenv("LANGFUSE_SECRET_KEY")
    client = None
    if public_key and secret_key:
        try:
            client = Langfuse(
                public_key=public_key, secret_key=secret_key,
                base_url=os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST") or None,
                timeout=5,
            )
        except Exception:
            logger.warning("Langfuse initialization failed")
    try:
        yield client
    finally:
        if client is not None:
            try:
                client.shutdown()
            except Exception:
                logger.warning("Langfuse shutdown failed")


@contextmanager
def observe(
    name: str, *, as_type: ObservationType, run_id: str | None = None, case_id: str | None = None,
    client: Langfuse | None = None, model: str | None = None,
) -> Iterator[Observation]:
    event = Observation()
    parent = current.get()
    if parent is not None and (run_id is None or run_id == parent.run_id):
        run_id, case_id = parent.run_id, parent.case_id
    else:
        parent = None
    if run_id is None or case_id is None:
        yield event
        return

    trace_id = parent.trace_id if parent else sha256(f"otif:{run_id}".encode()).hexdigest()[:32]
    identifiers = {"run_id": run_id, "case_id": case_id}
    span = None
    try:
        if parent is not None and parent.span is not None:
            span = parent.span.start_observation(name=name, as_type=as_type, model=model, metadata=identifiers)
        elif client is not None:
            span = client.start_observation(
                name=name, as_type=as_type, model=model, metadata=identifiers, trace_context={"trace_id": trace_id},
            )
    except Exception:
        logger.warning("Langfuse observation could not start")

    token = current.set(ActiveObservation(run_id, case_id, trace_id, span))
    started = perf_counter()
    outcome, error_type = "ok", None
    try:
        yield event
    except GraphInterrupt:
        outcome = "paused"
        raise
    except Exception as exc:
        outcome, error_type = "error", type(exc).__name__
        raise
    finally:
        current.reset(token)
        metadata = {
            **identifiers, "outcome": outcome, "duration_ms": round((perf_counter() - started) * 1000, 2),
        }
        if event.workflow_status:
            metadata["workflow_status"] = event.workflow_status
        if event.review_code:
            metadata["review_code"] = event.review_code
        if error_type:
            metadata["error_type"] = error_type
        logger.info(json.dumps({
            "event": name, "trace_id": trace_id, **metadata,
            **({"model": model} if model else {}), **({"usage": event.usage} if event.usage else {}),
        }))
        if span is not None:
            try:
                span.update(metadata=metadata, level="ERROR" if error_type else None, status_message=error_type,
                            usage_details=event.usage)
            except Exception:
                logger.warning("Langfuse observation could not update")
            finally:
                try:
                    span.end()
                except Exception:
                    logger.warning("Langfuse observation could not end")
