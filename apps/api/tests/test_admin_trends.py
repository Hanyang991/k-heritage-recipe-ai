"""Tests for ``POST /v1/admin/trends/refresh`` and
``GET /v1/admin/trends/debug``."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.jobs.refresh_trends import RefreshResult
from app.models.user import User, UserRole
from app.services.trends import (
    MultiSourceDiscovery,
    StaticCandidateProvider,
    TrendsAdapterError,
)
from app.services.trends.mock import MockTrendsAdapter


class _NamedStaticProvider:
    """Static candidate provider with a configurable ``name`` for tests."""

    def __init__(self, name: str, keywords: list[str]) -> None:
        self.name = name
        self._keywords = keywords

    def discover_candidates(self, today=None, limit=50):  # type: ignore[no-untyped-def]
        return list(self._keywords)


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


def test_non_admin_cannot_debug(client: TestClient) -> None:
    token = _register(client, "user-debug@example.com")
    r = client.get(
        "/v1/admin/trends/debug",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_unauthenticated_cannot_debug(client: TestClient) -> None:
    r = client.get("/v1/admin/trends/debug")
    assert r.status_code == 401


def test_admin_debug_returns_full_breakdown(client: TestClient) -> None:
    token = _admin_token(client, "admin-debug@example.com")
    adapter = MockTrendsAdapter()
    discovery = MultiSourceDiscovery(
        adapter,
        [
            StaticCandidateProvider(["쑥라떼"]),
            _NamedStaticProvider("llm_expansion", ["쑥라떼", "두바이강정"]),
        ],
    )
    with patch("app.routers.admin.get_trend_discovery", return_value=discovery):
        r = client.get(
            "/v1/admin/trends/debug",
            params={"today": "2025-05-12", "limit": 5},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    assert body["discovery_type"] == "multi_source"
    assert body["ref_date"] == "2025-05-12"
    assert body["limit"] == 5
    assert body["unique_candidate_count"] == 2
    provider_names = [p["name"] for p in body["providers"]]
    assert provider_names == ["static", "llm_expansion"]
    # The shared keyword reports both sources, in registration order.
    suk = next(r for r in body["ranked"] if r["keyword"] == "쑥라떼")
    assert suk["primary_source"] == "static"
    assert suk["all_sources"] == ["static", "llm_expansion"]
    # Solo-emitted keyword carries only its emitting source.
    dubai = next(r for r in body["ranked"] if r["keyword"] == "두바이강정")
    assert dubai["all_sources"] == ["llm_expansion"]


def test_admin_debug_supports_curated_discovery(client: TestClient) -> None:
    from app.services.trends import CuratedWatchlistDiscovery

    token = _admin_token(client, "admin-debug-curated@example.com")
    discovery = CuratedWatchlistDiscovery(MockTrendsAdapter(), candidates=["쑥라떼"])
    with patch("app.routers.admin.get_trend_discovery", return_value=discovery):
        r = client.get(
            "/v1/admin/trends/debug",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["discovery_type"] == "curated"
    assert len(body["providers"]) == 1
    assert body["providers"][0]["name"] == "curated_watchlist"
    for row in body["ranked"]:
        assert row["all_sources"] == [row["primary_source"]]


def test_admin_debug_defaults_today_to_today(client: TestClient) -> None:
    token = _admin_token(client, "admin-debug-default@example.com")
    discovery = MultiSourceDiscovery(MockTrendsAdapter(), [StaticCandidateProvider(["쑥라떼"])])
    with patch("app.routers.admin.get_trend_discovery", return_value=discovery):
        r = client.get(
            "/v1/admin/trends/debug",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["ref_date"] == date.today().isoformat()


def test_admin_debug_rejects_out_of_range_limit(client: TestClient) -> None:
    token = _admin_token(client, "admin-debug-limit@example.com")
    r = client.get(
        "/v1/admin/trends/debug",
        params={"limit": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


def test_admin_debug_maps_upstream_error_to_502(client: TestClient) -> None:
    token = _admin_token(client, "admin-debug-upstream@example.com")
    with patch(
        "app.routers.admin.get_trend_discovery",
        side_effect=TrendsAdapterError("Naver DataLab rejected credentials (401)"),
    ):
        r = client.get(
            "/v1/admin/trends/debug",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 502, r.text
    body = r.json()
    assert body["error"] == "TRENDS_UPSTREAM_ERROR"
