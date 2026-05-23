"""Tests for ``POST /v1/admin/trends/refresh``."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.jobs.refresh_trends import RefreshResult
from app.models.user import User, UserRole
from app.services.trends import TrendsAdapterError


def _register(client: TestClient, email: str) -> str:
    r = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "secret123"},
    )
    return r.json()["access_token"]


def _promote_to_admin(email: str) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one()
        user.role = UserRole.ADMIN
        db.commit()
    finally:
        db.close()


def _admin_token(client: TestClient, email: str = "admin-trends@example.com") -> str:
    _register(client, email)
    _promote_to_admin(email)
    return client.post(
        "/v1/auth/login",
        json={"email": email, "password": "secret123"},
    ).json()["access_token"]


def test_non_admin_cannot_refresh(client: TestClient) -> None:
    token = _register(client, "user-trends@example.com")
    r = client.post(
        "/v1/admin/trends/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_admin_refresh_returns_counts(client: TestClient) -> None:
    token = _admin_token(client)
    fake = RefreshResult(week_of=__import__("datetime").date(2025, 5, 12), inserted=4, updated=1)
    with patch("app.routers.admin.refresh_trends", return_value=fake) as mock_refresh:
        r = client.post(
            "/v1/admin/trends/refresh",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    assert body == {"week_of": "2025-05-12", "inserted": 4, "updated": 1}
    mock_refresh.assert_called_once()


def test_admin_refresh_maps_upstream_error_to_502(client: TestClient) -> None:
    token = _admin_token(client)
    with patch(
        "app.routers.admin.refresh_trends",
        side_effect=TrendsAdapterError("Naver DataLab rejected credentials (401)"),
    ):
        r = client.post(
            "/v1/admin/trends/refresh",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 502, r.text
    body = r.json()
    assert body["error"] == "TRENDS_UPSTREAM_ERROR"
    assert "Naver DataLab" in body["message"]
