from pathlib import Path
import sys

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("argon2")
pytest.importorskip("httpx")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.main import app

PASSWORD = "correct horse battery staple"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "k" * 48)
    monkeypatch.setenv("AUTH_DEMO_PASSWORD_HASH", PasswordHasher().hash(PASSWORD))
    return TestClient(app)


@pytest.mark.parametrize("username,role", [
    ("demo_associate", "dispute_associate"),
    ("demo_manager", "compliance_manager"),
    ("demo_admin", "admin"),
])
def test_login_then_me_returns_role(client, username, role):
    response = client.post("/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200
    token = response.json()["access_token"]
    me = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["role"] == role


def test_wrong_password_is_401(client):
    assert client.post("/login", json={"username": "demo_manager", "password": "nope"}).status_code == 401


def test_unknown_user_is_401(client):
    assert client.post("/login", json={"username": "ghost", "password": PASSWORD}).status_code == 401


def test_me_without_token_is_401(client):
    assert client.get("/me").status_code == 401


def test_short_signing_key_is_503(client, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "change-me")
    assert client.post("/login", json={"username": "demo_associate", "password": PASSWORD}).status_code == 503
