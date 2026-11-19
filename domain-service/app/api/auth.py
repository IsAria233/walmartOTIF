"""Verify the bearer identity issued by Auth Service."""

import os
from typing import Annotated, Literal
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ValidationError

bearer_scheme = HTTPBearer(auto_error=False, bearerFormat="JWT")


class AuthenticatedUser(BaseModel):
    user_id: UUID
    role: Literal["dispute_associate", "compliance_manager", "admin"]


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthenticatedUser:
    unauthorized = HTTPException(
        status_code=401,
        detail={"error": {"code": "invalid_token", "message": "Invalid or expired bearer token"}},
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    signing_key = os.getenv("JWT_SECRET", "")
    if len(signing_key.encode("utf-8")) < 32:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "identity_unavailable", "message": "JWT verification is not configured"}},
        )

    try:
        claims = jwt.decode(
            credentials.credentials,
            signing_key,
            algorithms=["HS256"],
            options={"require": ["sub", "role", "exp"]},
        )
        return AuthenticatedUser(user_id=claims["sub"], role=claims["role"])
    except (jwt.InvalidTokenError, ValidationError) as exc:
        raise unauthorized from exc
