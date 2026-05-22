"""Admin review queue tests."""

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.models.user import User, UserRole


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


def test_admin_can_list_pending_recipes(client: TestClient) -> None:
    user_token = _register(client, "user@example.com")
    client.post(
        "/v1/private/recipes/generate",
        headers={"Authorization": f"Bearer {user_token}"},
        json={
            "keyword": "쑥라떼",
            "region": "전라북도",
            "diet": "비건",
            "menu_type": "디저트 음료",
        },
    )

    admin_token = _register(client, "admin@example.com")
    _promote_to_admin("admin@example.com")
    # Re-login to refresh role claim
    admin_token = client.post(
        "/v1/auth/login",
        json={"email": "admin@example.com", "password": "secret123"},
    ).json()["access_token"]

    r = client.get("/v1/admin/recipes", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200, r.text
    assert len(r.json()) == 3


def test_non_admin_cannot_access_admin_routes(client: TestClient) -> None:
    user_token = _register(client, "regular@example.com")
    r = client.get("/v1/admin/recipes", headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 403


def test_admin_reject_requires_reason(client: TestClient) -> None:
    user_token = _register(client, "owner-reject@example.com")
    gen = client.post(
        "/v1/private/recipes/generate",
        headers={"Authorization": f"Bearer {user_token}"},
        json={
            "keyword": "쑥라떼",
            "region": "전라북도",
            "diet": "비건",
            "menu_type": "디저트 음료",
        },
    ).json()
    recipe_id = gen["candidates"][0]["id"]

    _register(client, "admin-reject@example.com")
    _promote_to_admin("admin-reject@example.com")
    admin_token = client.post(
        "/v1/auth/login",
        json={"email": "admin-reject@example.com", "password": "secret123"},
    ).json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Reject without reason → 400
    r = client.post(
        f"/v1/admin/recipes/{recipe_id}/status",
        headers=admin_headers,
        json={"status": "rejected", "rejection_reason": "   "},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"] == "REJECTION_REASON_REQUIRED"

    # Reject with reason → 200, reason is persisted and surfaced to the user
    r2 = client.post(
        f"/v1/admin/recipes/{recipe_id}/status",
        headers=admin_headers,
        json={"status": "rejected", "rejection_reason": "재료가 식약처 기준에 미달"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "rejected"
    assert r2.json()["rejection_reason"] == "재료가 식약처 기준에 미달"

    # User can see the reason on their detail view
    detail = client.get(
        f"/v1/private/recipes/{recipe_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    ).json()
    assert detail["status"] == "rejected"
    assert detail["rejection_reason"] == "재료가 식약처 기준에 미달"
