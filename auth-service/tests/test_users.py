from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import jwt
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.users import DEMO_USERS, ROLES, TOKEN_LIFETIME, decode_token, find_user, issue_token

KEY = "k" * 48


def test_one_seeded_user_per_role_with_unique_ids():
    assert sorted(u.role for u in DEMO_USERS.values()) == sorted(ROLES)
    assert len({u.user_id for u in DEMO_USERS.values()}) == len(DEMO_USERS)


@pytest.mark.parametrize("username,role", [
    ("demo_associate", "dispute_associate"),
    ("demo_manager", "compliance_manager"),
    ("demo_admin", "admin"),
])
def test_token_carries_user_id_and_role(username, role):
    user = find_user(username)
    claims = decode_token(issue_token(user, KEY), KEY)
    assert claims["sub"] == str(user.user_id)
    assert claims["role"] == role


def test_associate_id_is_unchanged():
    assert str(find_user("demo_associate").user_id) == "b8fe47fd-7f89-49bf-8fa9-e4c7da8c72f4"


def test_unknown_user_is_not_found():
    assert find_user("someone_else") is None
    assert find_user("DEMO_ASSOCIATE") is None


def test_token_expires_after_lifetime():
    issued = datetime.now(timezone.utc) - TOKEN_LIFETIME - timedelta(seconds=5)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(issue_token(find_user("demo_manager"), KEY, now=issued), KEY)


def test_token_signed_with_another_key_is_rejected():
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(issue_token(find_user("demo_admin"), KEY), "x" * 48)


def test_token_missing_role_is_rejected():
    token = jwt.encode({"sub": "abc", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}, KEY, algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(token, KEY)
