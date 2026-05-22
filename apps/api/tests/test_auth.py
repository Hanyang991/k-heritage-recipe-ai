"""Authentication endpoint tests."""

from fastapi.testclient import TestClient


def test_register_and_login_returns_tokens(client: TestClient) -> None:
    r = client.post(
        "/v1/auth/register",
        json={"email": "alice@example.com", "password": "supersecret"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"

    # Second register with same email -> 409
    r2 = client.post(
        "/v1/auth/register",
        json={"email": "alice@example.com", "password": "supersecret"},
    )
    assert r2.status_code == 409
    assert r2.json()["error"] == "EMAIL_TAKEN"

    # Login
    r3 = client.post(
        "/v1/auth/login",
        json={"email": "alice@example.com", "password": "supersecret"},
    )
    assert r3.status_code == 200
    assert r3.json()["access_token"]


def test_login_with_wrong_password_returns_401(client: TestClient) -> None:
    client.post(
        "/v1/auth/register",
        json={"email": "bob@example.com", "password": "rightpass1"},
    )
    r = client.post(
        "/v1/auth/login",
        json={"email": "bob@example.com", "password": "wrongpass2"},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "INVALID_CREDENTIALS"


def test_me_returns_current_user(client: TestClient) -> None:
    reg = client.post(
        "/v1/auth/register",
        json={"email": "carol@example.com", "password": "secret123", "display_name": "Carol"},
    ).json()
    token = reg["access_token"]
    r = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "carol@example.com"
    assert body["display_name"] == "Carol"
    assert body["subscription"]["plan"] == "free"


def test_me_without_token_returns_401(client: TestClient) -> None:
    r = client.get("/v1/auth/me")
    assert r.status_code == 401
