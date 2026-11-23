"""Shared test setup."""
import uuid

import pytest

from app.api.routers import require_identity
from app.main import app

SERVICE_CLAIMS = {"sub": str(uuid.UUID(int=1)), "role": "agent_service"}


@pytest.fixture(autouse=True)
def signed_in(request):
    """Tests call the API as agent-service unless marked `real_auth`, which checks the token itself."""
    if "real_auth" in request.keywords:
        yield
        return
    app.dependency_overrides[require_identity] = lambda: SERVICE_CLAIMS
    yield
    app.dependency_overrides.pop(require_identity, None)
