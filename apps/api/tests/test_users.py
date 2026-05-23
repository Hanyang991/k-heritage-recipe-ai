"""Profile / onboarding endpoint tests (PATCH /v1/private/users/me)."""

from fastapi.testclient import TestClient


def _register(client: TestClient, email: str = "onb@example.com") -> str:
    r = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "secret123"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def test_new_user_starts_with_onboarding_incomplete(client: TestClient) -> None:
    token = _register(client)
    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["onboarding_completed"] is False
    assert me["persona"] == ""
    assert me["preferred_regions"] == []
    assert me["preferred_keywords"] == []


def test_onboarding_patch_saves_persona_and_preferences(client: TestClient) -> None:
    token = _register(client, "complete@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.patch(
        "/v1/private/users/me",
        headers=headers,
        json={
            "display_name": "홍길동",
            "persona": "카페 사장",
            "preferred_regions": ["전국", "전라북도"],
            "preferred_keywords": ["쑥라떼", "오미자에이드"],
            "onboarding_completed": True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["display_name"] == "홍길동"
    assert body["persona"] == "카페 사장"
    assert body["preferred_regions"] == ["전국", "전라북도"]
    assert body["preferred_keywords"] == ["쑥라떼", "오미자에이드"]
    assert body["onboarding_completed"] is True

    # Persisted across a fresh /auth/me call.
    me = client.get("/v1/auth/me", headers=headers).json()
    assert me["onboarding_completed"] is True
    assert me["persona"] == "카페 사장"


def test_onboarding_patch_partial_update_only_changes_supplied_fields(
    client: TestClient,
) -> None:
    token = _register(client, "partial@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # First set everything.
    client.patch(
        "/v1/private/users/me",
        headers=headers,
        json={
            "persona": "홈베이커",
            "preferred_regions": ["서울"],
            "preferred_keywords": ["흑임자크림"],
            "onboarding_completed": True,
        },
    )
    # Then flip just one field.
    r = client.patch(
        "/v1/private/users/me",
        headers=headers,
        json={"onboarding_completed": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["onboarding_completed"] is False
    # Other fields untouched.
    assert body["persona"] == "홈베이커"
    assert body["preferred_regions"] == ["서울"]
    assert body["preferred_keywords"] == ["흑임자크림"]


def test_onboarding_patch_skip_path_marks_completed_without_setting_prefs(
    client: TestClient,
) -> None:
    token = _register(client, "skip@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.patch(
        "/v1/private/users/me",
        headers=headers,
        json={"onboarding_completed": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["onboarding_completed"] is True
    assert body["persona"] == ""
    assert body["preferred_regions"] == []
    assert body["preferred_keywords"] == []


def test_onboarding_patch_rejects_too_many_keywords(client: TestClient) -> None:
    token = _register(client, "many@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    r = client.patch(
        "/v1/private/users/me",
        headers=headers,
        json={"preferred_keywords": [f"키워드{i}" for i in range(25)]},
    )
    assert r.status_code == 422


def test_onboarding_patch_requires_auth(client: TestClient) -> None:
    r = client.patch(
        "/v1/private/users/me",
        json={"onboarding_completed": True},
    )
    assert r.status_code == 401
