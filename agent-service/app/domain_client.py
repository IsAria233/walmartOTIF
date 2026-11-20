"""The agent's only way to business data: domain-service's REST API."""
from __future__ import annotations

import os

import httpx


class DomainError(RuntimeError):
    def __init__(self, status_code: int, body: str):
        super().__init__(f"domain-service returned {status_code}: {body[:300]}")
        self.status_code = status_code


class DomainClient:
    def __init__(self, base_url: str | None = None, client: httpx.Client | None = None):
        root = (base_url or os.getenv("DOMAIN_SERVICE_URL", "http://localhost:8002")).rstrip("/")
        self._http = client or httpx.Client(base_url=f"{root}/api/v1", timeout=15.0)

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        response = self._http.request(method, path, json=body)
        if response.status_code >= 400:
            raise DomainError(response.status_code, response.text)
        return response.json()

    # Reads
    def get_case(self, case_id: str) -> dict:
        return self._call("GET", f"/investigation-cases/{case_id}")

    def get_context(self, fine_record_id: str) -> dict:
        return self._call("GET", f"/investigation-contexts/{fine_record_id}")

    # Writes: case workflow only. There is no call that changes a fine or issues a credit.
    def set_status(self, case_id: str, status: str, reason: str | None = None) -> dict:
        return self._call("PATCH", f"/investigation-cases/{case_id}/status", {"status": status, "reason": reason})

    def submit_finding(self, case_id: str, finding: dict) -> dict:
        return self._call("POST", f"/investigation-cases/{case_id}/findings", finding)

    # reuse_existing: a retried run gets the evaluation and outcome it already created.
    def evaluate(self, case_id: str, finding_id: str) -> dict:
        return self._call("POST", f"/investigation-cases/{case_id}/evaluate",
                          {"finding_id": finding_id, "reuse_existing": True})

    def create_outcome(self, case_id: str, evaluation_id: str) -> dict:
        return self._call("POST", f"/investigation-cases/{case_id}/outcome",
                          {"evaluation_id": evaluation_id, "reuse_existing": True})

    def record_handoff(self, case_id: str, run_id: str, reason: str, details: dict) -> dict:
        """Hand the case to a person, keeping what the agent found. Safe to repeat for the same run."""
        return self._call("PUT", f"/internal/investigation-cases/{case_id}/handoffs/{run_id}",
                          {"reason": reason, "details": details})

    def approval_status(self, case_id: str, outcome_id: str) -> str:
        """pending_approval | pending_manager_approval | approved | rejected"""
        page = 1
        while True:
            data = self._call("GET", f"/investigation-cases/{case_id}/outcome?page={page}&page_size=100")
            for item in data["items"]:
                if item["outcome"]["id"] == outcome_id:
                    return item["outcome"]["status"]
            if page >= data.get("total_pages", 1):
                raise DomainError(502, f"Outcome {outcome_id} is missing in domain-service")
            page += 1
