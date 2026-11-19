"""Seeded demo users and JWT helpers. No web framework imports, so it is easy to test."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

JWT_ALGORITHM = "HS256"
TOKEN_LIFETIME = timedelta(minutes=30)
ROLES = ("dispute_associate", "compliance_manager", "admin")


@dataclass(frozen=True)
class DemoUser:
    username: str
    user_id: UUID
    role: str


# Internal accounts are seeded; there is no public registration.
# All demo accounts share the password whose hash is in AUTH_DEMO_PASSWORD_HASH.
DEMO_USERS = {
    user.username: user
    for user in (
        DemoUser("demo_associate", UUID("b8fe47fd-7f89-49bf-8fa9-e4c7da8c72f4"), "dispute_associate"),
        DemoUser("demo_manager", UUID("5d0c3a52-9d0e-4a57-a3f1-2f6c1c7e8b11"), "compliance_manager"),
        DemoUser("demo_admin", UUID("e3a1f6c4-0b7d-4c1e-9a55-7c2d9f4b6a20"), "admin"),
    )
}


def find_user(username: str) -> DemoUser | None:
    return DEMO_USERS.get(username)


def issue_token(user: DemoUser, signing_key: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    claims = {"sub": str(user.user_id), "role": user.role, "exp": now + TOKEN_LIFETIME}
    return jwt.encode(claims, signing_key, algorithm=JWT_ALGORITHM)


def decode_token(token: str, signing_key: str) -> dict:
    """Return verified claims. Raises jwt.InvalidTokenError if the token is bad or expired."""
    return jwt.decode(
        token,
        signing_key,
        algorithms=[JWT_ALGORITHM],
        options={"require": ["sub", "role", "exp"]},
    )
