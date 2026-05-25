"""Tests for ``POST /v1/admin/heritage/index/backfill``."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.models.user import User, UserRole
from app.services.vector_search.backfill import BackfillReport
from app.services.vector_search.indexer import IndexResult


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


def _admin_token(client: TestClient, email: str = "admin-backfill@example.com") -> str:
    _register(client, email)
    _promote_to_admin(email)
    return client.post(
        "/v1/auth/login",
        json={"email": email, "password": "secret123"},
    ).json()["access_token"]


def _fake_report() -> BackfillReport:
    report = BackfillReport()
    report.queries_attempted = 3
    report.queries_succeeded = 3
    report.queries_failed = {}
    report.unique_docs_collected = 2
    report.docs_per_source = {"jangseogak": 2}
    report.index_result = IndexResult(upserted={"jangseogak": 2})
    return report


def test_non_admin_cannot_trigger_backfill(client: TestClient) -> None:
    token = _register(client, "user-backfill@example.com")
    r = client.post(
        "/v1/admin/heritage/index/backfill",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_anonymous_cannot_trigger_backfill(client: TestClient) -> None:
    r = client.post("/v1/admin/heritage/index/backfill")
    assert r.status_code == 401


def test_admin_empty_body_uses_settings_defaults(client: TestClient) -> None:
    token = _admin_token(client)
    fake = _fake_report()
    with patch(
        "app.routers.admin.run_heritage_backfill",
        return_value=fake,
    ) as mock_backfill:
        r = client.post(
            "/v1/admin/heritage/index/backfill",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    assert body["queries_attempted"] == 3
    assert body["queries_succeeded"] == 3
    assert body["unique_docs_collected"] == 2
    assert body["docs_per_source"] == {"jangseogak": 2}
    assert body["upserted_per_namespace"] == {"jangseogak": 2}
    assert body["total_upserted"] == 2

    # Confirm overrides were all None (settings drive the run).
    mock_backfill.assert_called_once_with(
        queries=None, per_query_limit=None, batch_size=None
    )


def test_admin_can_override_queries_and_limits(client: TestClient) -> None:
    token = _admin_token(client)
    fake = _fake_report()
    with patch(
        "app.routers.admin.run_heritage_backfill",
        return_value=fake,
    ) as mock_backfill:
        r = client.post(
            "/v1/admin/heritage/index/backfill",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "queries": ["떡", "전"],
                "per_query_limit": 12,
                "batch_size": 7,
            },
        )
    assert r.status_code == 200, r.text
    mock_backfill.assert_called_once_with(
        queries=["떡", "전"], per_query_limit=12, batch_size=7
    )


def test_admin_invalid_per_query_limit_rejected_at_schema(
    client: TestClient,
) -> None:
    token = _admin_token(client)
    r = client.post(
        "/v1/admin/heritage/index/backfill",
        headers={"Authorization": f"Bearer {token}"},
        json={"per_query_limit": 0},
    )
    # Pydantic ``gt=0`` validator → 422.
    assert r.status_code == 422


def test_admin_runner_value_error_maps_to_400(client: TestClient) -> None:
    token = _admin_token(client)
    with patch(
        "app.routers.admin.run_heritage_backfill",
        side_effect=ValueError("at least one non-empty query is required"),
    ):
        r = client.post(
            "/v1/admin/heritage/index/backfill",
            headers={"Authorization": f"Bearer {token}"},
            json={"queries": []},
        )
    # Empty list trips the runner's own validation; route turns it
    # into a 400 with the structured error envelope used elsewhere.
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["error"] == "INVALID_BACKFILL_CONFIG"
    assert "non-empty query" in body["message"]


def test_admin_report_surfaces_failed_queries(client: TestClient) -> None:
    token = _admin_token(client)
    report = BackfillReport()
    report.queries_attempted = 2
    report.queries_succeeded = 1
    report.queries_failed = {"의궤": "transient: HTTP 503"}
    report.unique_docs_collected = 1
    report.docs_per_source = {"jangseogak": 1}
    report.index_result = IndexResult(upserted={"jangseogak": 1})
    with patch(
        "app.routers.admin.run_heritage_backfill",
        return_value=report,
    ):
        r = client.post(
            "/v1/admin/heritage/index/backfill",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["queries_failed"] == {"의궤": "transient: HTTP 503"}
    assert body["queries_succeeded"] == 1
    assert body["total_upserted"] == 1


def test_admin_report_surfaces_errored_namespaces(client: TestClient) -> None:
    token = _admin_token(client)
    report = BackfillReport()
    report.queries_attempted = 1
    report.queries_succeeded = 1
    report.unique_docs_collected = 5
    report.docs_per_source = {"jangseogak": 3, "koreanstudies": 2}
    report.index_result = IndexResult(
        upserted={"jangseogak": 3},
        errored={"koreanstudies": 2},
    )
    with patch(
        "app.routers.admin.run_heritage_backfill",
        return_value=report,
    ):
        r = client.post(
            "/v1/admin/heritage/index/backfill",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["upserted_per_namespace"] == {"jangseogak": 3}
    assert body["errored_per_namespace"] == {"koreanstudies": 2}
    # total_upserted reflects only successful namespaces.
    assert body["total_upserted"] == 3
