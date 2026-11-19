"""Orchestrate one fine record investigation for one purchase order line."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Literal, Protocol, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field, ValidationError

Cause = Literal["C1", "C2", "C3", "C4", "C5"]
EvidenceSource = Literal["asn", "appointment_history", "gate_log", "po_versions", "receiving"]
ApprovalStatus = Literal["pending_approval", "pending_manager_approval", "approved", "rejected"]
RunStatus = ApprovalStatus | Literal["investigating", "out_of_scope", "needs_review"]

PENDING_APPROVAL = {"pending_approval", "pending_manager_approval"}


class InvestigationInput(TypedDict):
    run_id: str
    case_id: str
    fine_record_id: str


class CaseIntake(TypedDict):
    po_line_id: str
    freight_terms: str | None
    channel: str | None
    ships_to_us_dc: bool | None
    metric: str | None


class Evidence(TypedDict):
    record_id: str
    facts: dict[str, Any]


class InvestigationPlan(TypedDict):
    causes: list[Cause]
    sources: list[EvidenceSource]


PLANS: dict[str, InvestigationPlan] = {
    "on_time": {"causes": ["C1", "C2"], "sources": ["asn", "appointment_history", "gate_log"]},
    "in_full": {"causes": ["C3", "C4", "C5"], "sources": ["asn", "po_versions", "receiving"]},
}


class FindingFact(BaseModel):
    fact_key: str = Field(min_length=1, max_length=150)
    fact_value: str
    evidence_ids: list[str]


class Finding(BaseModel):
    cause_code: Cause | None = None
    summary: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    facts: list[FindingFact] = Field(default_factory=list)
    handoff_required: bool = False
    handoff_reason: str | None = None
    injection_detected: bool = False


class InvestigationState(InvestigationInput, total=False):
    case: CaseIntake
    plan: InvestigationPlan
    evidence: dict[EvidenceSource, list[Evidence]]
    finding: dict[str, Any]
    finding_id: str
    evaluation_id: str
    outcome_id: str
    status: RunStatus
    handoff_reason: str
    result: dict[str, Any]


class PolicyReviewRequired(Exception):
    """The Domain policy cannot evaluate this finding automatically."""


class EvidenceReadError(RuntimeError):
    """Domain evidence could not be fetched or verified."""


class EvidenceReader(Protocol):
    def read_evidence(
        self, case_id: str, fine_record_id: str, sources: list[EvidenceSource]
    ) -> dict[EvidenceSource, list[Evidence]]: ...


class InvestigationDomain(EvidenceReader, Protocol):
    def read_intake(self, case_id: str, fine_record_id: str) -> CaseIntake: ...

    def submit_finding(self, case_id: str, run_id: str, finding: dict[str, Any]) -> str: ...

    def evaluate(self, case_id: str, finding_id: str) -> str: ...

    def create_outcome(self, case_id: str, evaluation_id: str) -> str: ...

    def read_approval_status(self, case_id: str, outcome_id: str) -> ApprovalStatus: ...


FindCause = Callable[[CaseIntake, InvestigationPlan, dict[EvidenceSource, list[Evidence]]], Finding]


def build_investigation_graph(
    *,
    domain: InvestigationDomain,
    find_cause: FindCause,
    checkpointer: BaseCheckpointSaver,
    evidence_reader: EvidenceReader | None = None,
) -> CompiledStateGraph:
    reader = evidence_reader if evidence_reader is not None else domain

    def intake(state: InvestigationInput, config: RunnableConfig) -> dict[str, Any]:
        if config.get("configurable", {}).get("thread_id") != state["run_id"]:
            raise ValueError("thread_id must match run_id")
        case = domain.read_intake(state["case_id"], state["fine_record_id"])
        return {"case": case, "status": "investigating"}

    def scope_check(state: InvestigationState) -> dict[str, Any]:
        case = state["case"]
        if (
            case["freight_terms"] not in ("prepaid", None)
            or case["channel"] not in ("stores", None)
            or case["ships_to_us_dc"] is False
        ):
            return {"status": "out_of_scope"}
        if any(case[key] is None for key in ("freight_terms", "channel", "ships_to_us_dc")):
            return needs_review("Required scope data is missing")
        if case["metric"] not in PLANS:
            return needs_review("The fine metric is missing or unsupported")
        return {}

    def plan(state: InvestigationState) -> dict[str, Any]:
        return {"plan": PLANS[state["case"]["metric"]]}

    def investigate(state: InvestigationState) -> dict[str, Any]:
        sources = state["plan"]["sources"]
        try:
            evidence = reader.read_evidence(state["case_id"], state["fine_record_id"], sources)
        except EvidenceReadError as exc:
            return needs_review(str(exc))
        missing = [source for source in sources if source not in evidence or (
            source != "appointment_history" and not evidence[source]
        )]
        if missing:
            return needs_review(f"Missing evidence: {', '.join(missing)}")
        return {"evidence": evidence}

    def findings(state: InvestigationState) -> dict[str, Any]:
        try:
            finding = Finding.model_validate(find_cause(state["case"], state["plan"], state["evidence"]))
        except ValidationError:
            return needs_review("The finding failed structured validation")

        result = {"finding": finding.model_dump(mode="json")}
        if finding.injection_detected or finding.handoff_required:
            reason = finding.handoff_reason or (
                "Untrusted instructions detected in evidence" if finding.injection_detected else "Finding requires human review"
            )
            return {**result, **needs_review(reason)}
        if finding.cause_code not in state["plan"]["causes"]:
            return {**result, **needs_review("The cause is missing or does not fit the fine metric")}

        evidence_ids = {record["record_id"] for records in state["evidence"].values() for record in records}
        if not finding.facts or any(
            not fact.evidence_ids or not set(fact.evidence_ids).issubset(evidence_ids)
            for fact in finding.facts
        ):
            return {**result, **needs_review("One or more finding facts lack a valid evidence citation")}
        return result

    def submit_finding(state: InvestigationState) -> dict[str, Any]:
        finding_id = domain.submit_finding(state["case_id"], state["run_id"], state["finding"])
        return {"finding_id": finding_id}

    def rules_call(state: InvestigationState) -> dict[str, Any]:
        try:
            evaluation_id = domain.evaluate(state["case_id"], state["finding_id"])
        except PolicyReviewRequired as exc:
            return needs_review(str(exc))
        return {"evaluation_id": evaluation_id}

    def create_outcome(state: InvestigationState) -> dict[str, Any]:
        return {"outcome_id": domain.create_outcome(state["case_id"], state["evaluation_id"])}

    def route(state: InvestigationState) -> dict[str, Any]:
        return {"status": domain.read_approval_status(state["case_id"], state["outcome_id"])}

    def approval_pause(state: InvestigationState) -> dict[str, Any]:
        interrupt({"case_id": state["case_id"], "outcome_id": state["outcome_id"], "status": state["status"]})
        return {}

    def finalize(state: InvestigationState) -> dict[str, Any]:
        fields = ("run_id", "case_id", "fine_record_id", "status", "finding_id", "evaluation_id", "outcome_id", "handoff_reason")
        return {"result": {key: state[key] for key in fields if key in state}}

    graph = StateGraph(InvestigationState, input_schema=InvestigationInput)
    graph.add_node("intake", intake)
    graph.add_node("scope_check", scope_check)
    graph.add_node("plan", plan)
    graph.add_node("investigate", investigate)
    graph.add_node("findings", findings)
    graph.add_node("submit_finding", submit_finding)
    graph.add_node("rules_call", rules_call)
    graph.add_node("create_outcome", create_outcome)
    graph.add_node("route", route)
    graph.add_node("approval_pause", approval_pause)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "scope_check")
    graph.add_edge("plan", "investigate")
    graph.add_edge("submit_finding", "rules_call")
    graph.add_edge("create_outcome", "route")
    graph.add_edge("approval_pause", "route")
    graph.add_edge("finalize", END)
    for origin, next_node in (
        ("scope_check", "plan"), ("investigate", "findings"),
        ("findings", "submit_finding"), ("rules_call", "create_outcome"),
    ):
        graph.add_conditional_edges(origin, is_handoff_or_out_of_scope, {True: "finalize", False: next_node})
    graph.add_conditional_edges(
        "route", lambda state: state["status"] in PENDING_APPROVAL,
        {True: "approval_pause", False: "finalize"},
    )
    return graph.compile(checkpointer=checkpointer)


def needs_review(reason: str) -> dict[str, str]:
    return {"status": "needs_review", "handoff_reason": reason}


def is_handoff_or_out_of_scope(state: InvestigationState) -> bool:
    return state["status"] in {"needs_review", "out_of_scope"}


@contextmanager
def open_investigation_graph(
    checkpoint_dsn: str,
    *,
    domain: InvestigationDomain,
    find_cause: FindCause,
    evidence_reader: EvidenceReader | None = None,
) -> Iterator[CompiledStateGraph]:
    with PostgresSaver.from_conn_string(checkpoint_dsn) as checkpointer:
        checkpointer.setup()
        yield build_investigation_graph(
            domain=domain, find_cause=find_cause, checkpointer=checkpointer, evidence_reader=evidence_reader,
        )
