"""Shared test setup."""
import uuid

import pytest

from app.api.routers import admin_only, agent_only, require_identity
from app.main import app

SERVICE_CLAIMS = {"sub": str(uuid.UUID(int=1)), "role": "agent_service"}


@pytest.fixture(autouse=True)
def signed_in(request):
    """Tests are signed in and pass every role check unless marked `real_auth`, which sends real tokens."""
    if "real_auth" in request.keywords:
        yield
        return
    checks = (require_identity, agent_only, admin_only)
    for check in checks:
        app.dependency_overrides[check] = lambda: SERVICE_CLAIMS
    yield
    for check in checks:
        app.dependency_overrides.pop(check, None)
