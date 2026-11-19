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


@contextmanager
def investigation_trace(case_id: str, run_id: str):
    """Root of the trace. Yields (observation, trace_id); trace_id is None when tracing is off."""
    if not enabled():
        yield _Noop(), None
        return
    from langfuse import get_client, propagate_attributes

    client = get_client()
    try:
        with propagate_attributes(trace_name="otif-investigation", session_id=case_id,
                                  tags=["otif", f"case:{case_id}"], metadata={"run_id": run_id}):
            with client.start_as_current_observation(name="otif-investigation", as_type="agent",
                                                     input={"case_id": case_id}) as root:
                yield root, client.get_current_trace_id()
    finally:
        client.flush()
