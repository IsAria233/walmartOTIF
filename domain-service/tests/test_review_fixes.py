"""Caller identity and approval-stage roles (domain verifies the Auth Service JWT)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

import jwt
import pytest
from fastapi import HTTPException

from app.api import routers

SECRET = "k" * 48


def request_with(token: str | None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return SimpleNamespace(headers=headers)


def token(role: str, *, minutes: int = 5, sub: str | None = None, key: str = SECRET) -> str:
    claims = {"sub": sub or str(uuid.uuid4()), "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes)}
    return jwt.encode(claims, key, algorithm="HS256")


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)


def test_valid_token_gives_user_and_role():
    user_id = str(uuid.uuid4())
    request = request_with(token("compliance_manager", sub=user_id))
    assert str(routers.authenticated_user(request)) == user_id
    assert routers.authenticated_role(request) == "compliance_manager"


@pytest.mark.parametrize("bad", [None, "not-a-jwt"])
def test_missing_or_malformed_token_is_401(bad):
    with pytest.raises(HTTPException) as error:
        routers.authenticated_user(request_with(bad))
    assert error.value.status_code == 401


def test_expired_or_foreign_token_is_401():
    for bad in (token("dispute_associate", minutes=-5), token("dispute_associate", key="x" * 48)):
        with pytest.raises(HTTPException) as error:
            routers.authenticated_role(request_with(bad))
        assert error.value.status_code == 401


def test_unknown_role_is_403():
    with pytest.raises(HTTPException) as error:
        routers.authenticated_role(request_with(token("supplier")))
    assert error.value.status_code == 403


def test_short_secret_is_503(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "change-me")
    with pytest.raises(HTTPException) as error:
        routers.authenticated_user(request_with(token("admin")))
    assert error.value.status_code == 503


def test_only_a_manager_may_record_the_manager_stage():
    assert routers.STAGE_ROLES["manager"] == {"compliance_manager"}
    assert "dispute_associate" in routers.STAGE_ROLES["associate"]
    assert "admin" not in routers.STAGE_ROLES["associate"] | routers.STAGE_ROLES["manager"]
