"""Auth service for internal users."""

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, SecretStr, ValidationError

app = FastAPI(title="auth-service")
password_hasher = PasswordHasher()
bearer_scheme = HTTPBearer(auto_error=False, bearerFormat="JWT")
JWT_ALGORITHM = "HS256"
TOKEN_LIFETIME = timedelta(minutes=30)
Role = Literal["dispute_associate", "compliance_manager", "admin"]


class LoginRequest(BaseModel):
    username: str
    password: SecretStr


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class AuthenticatedUser(BaseModel):
    user_id: UUID
    role: Role


@dataclass(frozen=True)
class DemoAccount:
    user_id: UUID
    role: Role
    password_hash_env: str


DEMO_ACCOUNTS = {
    "demo_associate": DemoAccount(
        UUID("b8fe47fd-7f89-49bf-8fa9-e4c7da8c72f4"),
        "dispute_associate",
        "AUTH_DEMO_PASSWORD_HASH",
    ),
    "demo_manager": DemoAccount(
        UUID("f5eb6973-600d-4319-939c-548d423b52e5"),
        "compliance_manager",
        "AUTH_DEMO_MANAGER_PASSWORD_HASH",
    ),
}


def get_signing_key() -> str:
    signing_key = os.getenv("JWT_SECRET", "")
    if len(signing_key.encode("utf-8")) < 32:
        raise HTTPException(status_code=503, detail="Auth service is not configured")
    return signing_key


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthenticatedUser:
    unauthorized = HTTPException(
        status_code=401,
        detail="Invalid or expired bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    try:
        claims = jwt.decode(
            credentials.credentials,
            get_signing_key(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "role", "exp"]},
        )
        return AuthenticatedUser(user_id=claims["sub"], role=claims["role"])
    except (jwt.InvalidTokenError, ValidationError) as exc:
        raise unauthorized from exc


@app.exception_handler(RequestValidationError)
async def invalid_request(_request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": details})


@app.get("/health")
def health():
    return {"service": "auth-service", "status": "ok"}


@app.post("/login", response_model=LoginResponse)
def login(credentials: LoginRequest, response: Response) -> LoginResponse:
    signing_key = get_signing_key()
    demo_hashes = {
        username: os.getenv(account.password_hash_env)
        for username, account in DEMO_ACCOUNTS.items()
    }
    account_hash = demo_hashes.get(credentials.username)
    verification_hash = account_hash or next((value for value in demo_hashes.values() if value), None)
    if not verification_hash:
        raise HTTPException(status_code=503, detail="Auth service is not configured")

    try:
        password_matches = password_hasher.verify(verification_hash, credentials.password.get_secret_value())
    except VerifyMismatchError:
        password_matches = False
    except (InvalidHashError, VerificationError) as exc:
        raise HTTPException(status_code=503, detail="Auth service is not configured") from exc

    if not account_hash or not password_matches:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    account = DEMO_ACCOUNTS[credentials.username]
    access_token = jwt.encode(
        {
            "sub": str(account.user_id),
            "role": account.role,
            "exp": datetime.now(timezone.utc) + TOKEN_LIFETIME,
        },
        signing_key,
        algorithm=JWT_ALGORITHM,
    )
    response.headers["Cache-Control"] = "no-store"
    return LoginResponse(access_token=access_token)


@app.get("/me", response_model=AuthenticatedUser)
def me(
    response: Response,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AuthenticatedUser:
    response.headers["Cache-Control"] = "no-store"
    return current_user
