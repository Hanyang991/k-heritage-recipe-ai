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

    r = client.get(
        "/v1/admin/recipes", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 3


def test_non_admin_cannot_access_admin_routes(client: TestClient) -> None:
    user_token = _register(client, "regular@example.com")
    r = client.get(
        "/v1/admin/recipes", headers={"Authorization": f"Bearer {user_token}"}
    )
    assert r.status_code == 403
