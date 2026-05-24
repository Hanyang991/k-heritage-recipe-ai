"""Tests for ``/v1/private/me/favorite-keywords``."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _register(client: TestClient, email: str = "fav@example.org") -> str:
    r = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "secret123"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_list_starts_empty(client: TestClient) -> None:
    token = _register(client)
    r = client.get("/v1/private/me/favorite-keywords", headers=_auth(token))
    assert r.status_code == 200
    assert r.json() == []


def test_post_creates_and_get_returns_them(client: TestClient) -> None:
    token = _register(client)
    r1 = client.post(
        "/v1/private/me/favorite-keywords",
        json={"keyword": "두바이쫀득쿠키"},
        headers=_auth(token),
    )
    assert r1.status_code == 201, r1.text
    body = r1.json()
    assert body["keyword"] == "두바이쫀득쿠키"
    assert body["id"]
    assert body["created_at"]

    r2 = client.post(
        "/v1/private/me/favorite-keywords",
        json={"keyword": "약과"},
        headers=_auth(token),
    )
    assert r2.status_code == 201

    listing = client.get("/v1/private/me/favorite-keywords", headers=_auth(token)).json()
    # ``created_at`` resolution is per-second on SQLite, so two posts in the
    # same test run can tie; assert membership rather than order.
    assert {row["keyword"] for row in listing} == {"두바이쫀득쿠키", "약과"}


def test_post_is_idempotent(client: TestClient) -> None:
    """Re-starring an existing keyword returns the same row, not a duplicate.

    The frontend star toggle doesn't track "did I already star this?" — it
    just calls POST when the user clicks. Idempotency keeps the table clean
    and the UX optimistic.
    """
    token = _register(client)
    first = client.post(
        "/v1/private/me/favorite-keywords",
        json={"keyword": "약과"},
        headers=_auth(token),
    ).json()
    second = client.post(
        "/v1/private/me/favorite-keywords",
        json={"keyword": "약과"},
        headers=_auth(token),
    ).json()
    assert first["id"] == second["id"]
    listing = client.get("/v1/private/me/favorite-keywords", headers=_auth(token)).json()
    assert len(listing) == 1


def test_delete_removes(client: TestClient) -> None:
    token = _register(client)
    client.post(
        "/v1/private/me/favorite-keywords",
        json={"keyword": "약과"},
        headers=_auth(token),
    )
    r = client.delete("/v1/private/me/favorite-keywords/약과", headers=_auth(token))
    assert r.status_code == 204
    listing = client.get("/v1/private/me/favorite-keywords", headers=_auth(token)).json()
    assert listing == []


def test_delete_unknown_keyword_returns_404(client: TestClient) -> None:
    token = _register(client)
    r = client.delete(
        "/v1/private/me/favorite-keywords/존재안함",
        headers=_auth(token),
    )
    assert r.status_code == 404
    body = r.json()
    assert body["error"] == "FAVORITE_NOT_FOUND"


def test_favorites_are_per_user(client: TestClient) -> None:
    """User A starring a keyword does not surface it in User B's list."""
    token_a = _register(client, email="a@example.org")
    token_b = _register(client, email="b@example.org")
    client.post(
        "/v1/private/me/favorite-keywords",
        json={"keyword": "약과"},
        headers=_auth(token_a),
    )
    a_listing = client.get("/v1/private/me/favorite-keywords", headers=_auth(token_a)).json()
    b_listing = client.get("/v1/private/me/favorite-keywords", headers=_auth(token_b)).json()
    assert [r["keyword"] for r in a_listing] == ["약과"]
    assert b_listing == []


def test_anonymous_access_is_rejected(client: TestClient) -> None:
    r = client.get("/v1/private/me/favorite-keywords")
    assert r.status_code == 401


def test_empty_keyword_is_rejected(client: TestClient) -> None:
    token = _register(client)
    r = client.post(
        "/v1/private/me/favorite-keywords",
        json={"keyword": "   "},
        headers=_auth(token),
    )
    assert r.status_code == 422


def test_keyword_whitespace_is_stripped(client: TestClient) -> None:
    token = _register(client)
    r = client.post(
        "/v1/private/me/favorite-keywords",
        json={"keyword": "  약과  "},
        headers=_auth(token),
    )
    assert r.status_code == 201
    assert r.json()["keyword"] == "약과"
