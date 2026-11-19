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

    def evaluate(self, case_id: str, finding_id: str) -> dict:
        return self._call("POST", f"/investigation-cases/{case_id}/evaluate", {"finding_id": finding_id})

    def create_outcome(self, case_id: str, evaluation_id: str) -> dict:
        return self._call("POST", f"/investigation-cases/{case_id}/outcome", {"evaluation_id": evaluation_id})
