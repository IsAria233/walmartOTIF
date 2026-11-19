"""Connect the HTTP API to the checkpoint database and the Domain client."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from typing import TYPE_CHECKING
from uuid import UUID

import psycopg
from fastapi import HTTPException
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .api import InvestigationRuntime
from .domain_investigation import DomainInvestigationClient
from .investigation import FindCause, FindingAnalysisError, build_investigation_graph

if TYPE_CHECKING:
    from langfuse import Langfuse


def _missing_analyzer(case, plan, evidence):
    raise FindingAnalysisError("Finding model is not configured")


@contextmanager
def _lock_case(dsn: str, case_id: UUID) -> Iterator[None]:
    lock_id = int.from_bytes(case_id.bytes[:8], byteorder="big", signed=True)
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
        acquired = conn.execute("SELECT pg_try_advisory_lock(%s)", (lock_id,)).fetchone()[0]
        if not acquired:
            raise HTTPException(409, "Another investigation request for this case is in progress")
        yield


@contextmanager
def open_runtime(
    checkpoint_dsn: str, domain: DomainInvestigationClient, find_cause: FindCause | None,
    *, langfuse: "Langfuse | None" = None,
) -> Iterator[InvestigationRuntime]:
    with ConnectionPool(
        checkpoint_dsn, min_size=1, max_size=4, open=False, timeout=10,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    ) as pool:
        pool.wait()
        saver = PostgresSaver(pool)
        saver.setup()
        graph = build_investigation_graph(
            domain=domain, find_cause=find_cause or _missing_analyzer, checkpointer=saver,
        )
        yield InvestigationRuntime(
            graph=graph, get_case=domain.get_case, lock_case=partial(_lock_case, checkpoint_dsn),
            model_available=find_cause is not None, langfuse=langfuse,
        )
