"""Auth service: login, JWT issuing, roles.

Roles: dispute_associate, compliance_manager, dc_ops_viewer, admin.
Accounts are seeded for the demo (no public registration).
"""
from fastapi import FastAPI

app = FastAPI(title="auth-service")


@app.get("/health")
def health():
    return {"service": "auth-service", "status": "ok"}


# TODO: POST /login -> JWT with user id and role
# TODO: GET /me -> current user
# TODO: seed script for demo accounts
