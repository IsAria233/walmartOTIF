"""LangFuse tracing: one trace per investigation, a span per model step and per tool call.

Tracing is on when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set, and a
no-op otherwise, so tests and key-less runs behave the same way.
"""
from __future__ import annotations

import os
from contextlib import contextmanager


def enabled() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


class _Noop:
    def update(self, **_kwargs) -> None:
        pass


def plain(value):
    """SDK objects and test doubles as JSON-ready data."""
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if hasattr(value, "__dict__"):
        return plain(vars(value))
    return value


@contextmanager
def observation(name: str, as_type: str = "span", **kwargs):
    if not enabled():
        yield _Noop()
        return
    from langfuse import get_client

    with get_client().start_as_current_observation(name=name, as_type=as_type, **kwargs) as current:
        yield current


def trace_id_for(run_id: str) -> str | None:
    """The trace of a run, derived from its id so every request for the run lands in one trace."""
    if not enabled():
        return None
    from langfuse import get_client

    return get_client().create_trace_id(seed=run_id)


@contextmanager
def investigation_trace(case_id: str, run_id: str, phase: str = "start"):
    """One request's part of a run's trace: start, retry, or resume after approval."""
    if not enabled():
        yield _Noop()
        return
    from langfuse import get_client, propagate_attributes

    client = get_client()
    try:
        with propagate_attributes(trace_name="otif-investigation", session_id=case_id,
                                  tags=["otif", f"case:{case_id}"], metadata={"run_id": run_id}):
            with client.start_as_current_observation(
                trace_context={"trace_id": trace_id_for(run_id)}, name=f"investigation.{phase}",
                as_type="agent", input={"case_id": case_id, "run_id": run_id},
            ) as root:
                yield root
    finally:
        client.flush()
