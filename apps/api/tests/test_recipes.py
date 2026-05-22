"""Recipe generation + CRUD tests using the mock LLM/heritage adapters."""

from fastapi.testclient import TestClient


def _register(client: TestClient, email: str = "rec@example.com") -> str:
    r = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "secret123"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def test_generate_returns_3_candidates(client: TestClient) -> None:
    token = _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    r = client.post(
        "/v1/private/recipes/generate",
        headers=headers,
        json={
            "keyword": "쑥라떼",
            "region": "전라북도",
            "diet": "비건",
            "menu_type": "디저트 음료",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["candidates"]) == 3
    first = body["candidates"][0]
    assert first["is_recommended"] is True
    assert first["name"]
    assert first["status"] == "pending_review"
    assert len(body["matched_documents"]) >= 1


def test_list_then_get_then_delete_recipe(client: TestClient) -> None:
    token = _register(client, "crud@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    gen = client.post(
        "/v1/private/recipes/generate",
        headers=headers,
        json={
            "keyword": "오미자에이드",
            "region": "제주",
            "diet": "제한 없음",
            "menu_type": "디저트 음료",
        },
    ).json()
    recipe_id = gen["candidates"][0]["id"]

    lst = client.get("/v1/private/recipes", headers=headers)
    assert lst.status_code == 200
    assert len(lst.json()) == 3

    detail = client.get(f"/v1/private/recipes/{recipe_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["name"]
    assert len(body["ingredients"]) > 0
    assert len(body["steps"]) > 0

    delete = client.delete(f"/v1/private/recipes/{recipe_id}", headers=headers)
    assert delete.status_code == 204

    lst2 = client.get("/v1/private/recipes", headers=headers)
    assert len(lst2.json()) == 2


def test_free_plan_quota_enforced(client: TestClient) -> None:
    token = _register(client, "quota@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "keyword": "흑임자크림",
        "region": "경상도",
        "diet": "비건",
        "menu_type": "디저트 음료",
    }
    for _ in range(3):
        r = client.post("/v1/private/recipes/generate", headers=headers, json=payload)
        assert r.status_code == 200, r.text

    r4 = client.post("/v1/private/recipes/generate", headers=headers, json=payload)
    assert r4.status_code == 429
    assert r4.json()["error"] == "RECIPE_QUOTA_EXCEEDED"


def test_pdf_export_returns_pdf(client: TestClient) -> None:
    token = _register(client, "pdf@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    gen = client.post(
        "/v1/private/recipes/generate",
        headers=headers,
        json={
            "keyword": "쑥라떼",
            "region": "전라북도",
            "diet": "비건",
            "menu_type": "디저트 음료",
        },
    ).json()
    recipe_id = gen["candidates"][0]["id"]
    r = client.get(f"/v1/private/recipes/{recipe_id}/export/pdf", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"


def test_update_recipe_rating_and_is_selling(client: TestClient) -> None:
    token = _register(client, "rate@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    gen = client.post(
        "/v1/private/recipes/generate",
        headers=headers,
        json={
            "keyword": "오미자에이드",
            "region": "제주",
            "diet": "제한 없음",
            "menu_type": "디저트 음료",
        },
    ).json()
    recipe_id = gen["candidates"][0]["id"]

    r = client.patch(
        f"/v1/private/recipes/{recipe_id}",
        headers=headers,
        json={"rating": 4, "is_selling": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rating"] == 4
    assert body["is_selling"] is True

    # Partial update — only flip is_selling, rating unchanged
    r2 = client.patch(
        f"/v1/private/recipes/{recipe_id}",
        headers=headers,
        json={"is_selling": False},
    )
    assert r2.status_code == 200
    assert r2.json()["rating"] == 4
    assert r2.json()["is_selling"] is False


def test_update_recipe_rejects_out_of_range_rating(client: TestClient) -> None:
    token = _register(client, "rate-bad@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    gen = client.post(
        "/v1/private/recipes/generate",
        headers=headers,
        json={
            "keyword": "쑥라떼",
            "region": "전라북도",
            "diet": "비건",
            "menu_type": "디저트 음료",
        },
    ).json()
    recipe_id = gen["candidates"][0]["id"]
    r = client.patch(
        f"/v1/private/recipes/{recipe_id}",
        headers=headers,
        json={"rating": 9},
    )
    assert r.status_code == 422


def test_update_recipe_requires_ownership(client: TestClient) -> None:
    owner_token = _register(client, "owner@example.com")
    gen = client.post(
        "/v1/private/recipes/generate",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "keyword": "오미자에이드",
            "region": "제주",
            "diet": "제한 없음",
            "menu_type": "디저트 음료",
        },
    ).json()
    recipe_id = gen["candidates"][0]["id"]

    other_token = _register(client, "intruder@example.com")
    r = client.patch(
        f"/v1/private/recipes/{recipe_id}",
        headers={"Authorization": f"Bearer {other_token}"},
        json={"rating": 1},
    )
    assert r.status_code == 404


def test_certificate_blocked_on_free_plan(client: TestClient) -> None:
    token = _register(client, "cert@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    gen = client.post(
        "/v1/private/recipes/generate",
        headers=headers,
        json={
            "keyword": "쑥라떼",
            "region": "전라북도",
            "diet": "비건",
            "menu_type": "디저트 음료",
        },
    ).json()
    recipe_id = gen["candidates"][0]["id"]
    r = client.get(f"/v1/private/recipes/{recipe_id}/certificate", headers=headers)
    assert r.status_code == 402
    assert r.json()["error"] == "PLAN_REQUIRED"
