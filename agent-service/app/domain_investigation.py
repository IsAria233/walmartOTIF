"""Write investigation results to Domain and read the resulting approval."""

from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError

from .domain_evidence import DomainEvidenceReader
from .investigation import ApprovalStatus, Evidence, EvidenceSource, HandoffDetails, PolicyReviewRequired

READY_TO_INVESTIGATE = {"pending", "investigating", "revision_required", "handed_off"}


class DomainRequestError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class DomainCase(BaseModel):
    id: UUID
    fine_record_id: UUID
    status: str


class DomainOutcome(BaseModel):
    id: UUID
    status: ApprovalStatus


class DomainInvestigationClient(DomainEvidenceReader):
    def get_case(self, case_id: str) -> DomainCase:
        payload = self._request("GET", f"/api/v1/investigation-cases/{case_id}", case_lookup=True)
        try:
            case = DomainCase.model_validate(payload)
            if str(case.id) != case_id:
                raise ValueError("Case ID mismatch")
            return case
        except (ValidationError, ValueError) as exc:
            raise DomainRequestError(502, "Domain returned an invalid case") from exc

    def submit_finding(
        self, case_id: str, run_id: str, finding: dict[str, Any], evidence: dict[EvidenceSource, list[Evidence]],
    ) -> str:
        path = f"/api/v1/investigation-cases/{case_id}"
        case = self.get_case(case_id)
        if case.status in READY_TO_INVESTIGATE and case.status != "investigating":
            self._request("PATCH", f"{path}/status", json={"status": "investigating", "reason": "Agent investigation"})
        sources = {row["record_id"]: source for source, rows in evidence.items() for row in rows}
        facts = []
        for fact in finding["facts"]:
            citations = list(dict.fromkeys(fact["evidence_ids"]))
            facts.append({
                "fact_key": fact["fact_key"],
                "fact_value": fact["fact_value"],
                "source_refs": [{"source": sources[citation], "record_id": citation} for citation in citations],
            })
        payload = self._request("POST", f"{path}/findings", json={**finding, "facts": facts, "agent_run_id": run_id})
        return self._id(payload)

    def evaluate(self, case_id: str, finding_id: str) -> str:
        response = self._request(
            "POST", f"/api/v1/investigation-cases/{case_id}/evaluate",
            json={"finding_id": finding_id, "reuse_existing": True}, policy_evaluation=True,
        )
        return self._id(response)

    def create_outcome(self, case_id: str, evaluation_id: str) -> str:
        response = self._request(
            "POST", f"/api/v1/investigation-cases/{case_id}/outcome",
            json={"evaluation_id": evaluation_id, "reuse_existing": True},
        )
        return self._id(response)

    def record_handoff(self, case_id: str, run_id: str, reason: str, details: HandoffDetails) -> str:
        payload = self._request(
            "PUT", f"/api/v1/internal/investigation-cases/{case_id}/handoffs/{run_id}",
            json={"reason": reason, "details": details},
        )
        return self._id(payload)

    def read_approval_status(self, case_id: str, outcome_id: str) -> ApprovalStatus:
        path = f"/api/v1/investigation-cases/{case_id}/outcome"
        page = 1
        while True:
            response = self._request("GET", path, params={"page": page, "page_size": 100})
            try:
                for item in response["items"]:
                    outcome = DomainOutcome.model_validate(item["outcome"])
                    if str(outcome.id) == outcome_id:
                        return outcome.status
                if page >= response["total_pages"]:
                    break
            except (KeyError, TypeError, ValidationError) as exc:
                raise DomainRequestError(502, "Domain returned an invalid outcome list") from exc
            page += 1
        raise DomainRequestError(502, "Investigation outcome is missing in Domain")

    def _request(
        self, method: str, path: str, *, case_lookup: bool = False, policy_evaluation: bool = False, **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise DomainRequestError(503, "Domain service is unavailable") from exc
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object")
        except ValueError as exc:
            raise DomainRequestError(502, "Domain returned an invalid response") from exc
        if response.is_success:
            return payload
        if case_lookup and response.status_code == 404:
            raise DomainRequestError(404, "Investigation case not found")
        if response.status_code == 409:
            error = payload.get("error") or {}
            if policy_evaluation and error.get("code") == "policy_unavailable":
                raise PolicyReviewRequired(error.get("message") or "Domain policy requires human review")
            raise DomainRequestError(409, "Domain case or outcome changed")
        raise DomainRequestError(502, "Domain could not complete the investigation request")

    @staticmethod
    def _id(payload: dict[str, Any]) -> str:
        try:
            return str(UUID(payload["id"]))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise DomainRequestError(502, "Domain returned an invalid result identifier") from exc
