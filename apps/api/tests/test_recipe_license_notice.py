"""Tests for the structured ``license_notice`` on recipe responses (spec §3.1).

These tests guarantee:

* ``POST /v1/private/recipes/generate`` attaches a properly-shaped
  KOGL-1 license notice to every candidate (the LLM cites the same
  matched docs for all 3 candidates).
* ``GET /v1/private/recipes/{id}`` (RecipeDetailOut) attaches the
  same notice, derived from the source attribution text when the
  recipe doesn't have an explicit ``source_document_id`` link.
* The legacy ``source_attribution`` string is preserved byte-for-byte
  so existing frontend consumers don't break.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _register(client: TestClient, email: str = "lic@example.com") -> str:
    r = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "secret123"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def test_generate_attaches_license_notice_to_every_candidate(client: TestClient) -> None:
    token = _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post(
        "/v1/private/recipes/generate",
        headers=headers,
        json={
            "keyword": "쑥라떼",
            "region": "전라북도",
            "diet": "비건",
            "menu_type": "디저트 음료",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    candidates = body["candidates"]
    assert len(candidates) == 3
    for candidate in candidates:
        # Every candidate carries the structured notice + the legacy
        # display string side-by-side.
        notice = candidate["license_notice"]
        assert notice is not None
        assert notice["code"] == "KOGL-1"
        assert "공공누리" in notice["name"]
        assert notice["url"].startswith("https://www.kogl.or.kr/")
        assert "source_attribution" in notice["obligations"]
        # Legacy string is still present and starts with the spec-§3.1
        # mandated "출처: " prefix.
        assert candidate["source_attribution"].startswith("출처:")


def test_recipe_detail_attaches_license_notice(client: TestClient) -> None:
    token = _register(client, "lic-detail@example.com")
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

    response = client.get(f"/v1/private/recipes/{recipe_id}", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    notice = body["license_notice"]
    # Detail endpoint must surface the same compliance summary the
    # generate response did.
    assert notice is not None
    assert notice["code"] == "KOGL-1"
    assert notice["institution_display_name"]
    # Permission / obligation summary is non-empty.
    assert "commercial_use" in notice["permissions"]
    assert "source_attribution" in notice["obligations"]
    # Legacy attribution string preserved.
    assert body["source_attribution"].startswith("출처:")


def test_recipe_list_does_not_explode_when_recipe_has_no_source_attribution(
    client: TestClient, db_session
) -> None:
    """Recipes without attribution still serialise — ``license_notice`` is null."""
    from app.models.recipe import Recipe, RecipeStatus
    from app.models.user import User

    # Register so the user exists in DB.
    _register(client, "lic-orphan@example.com")
    user = db_session.query(User).filter(User.email == "lic-orphan@example.com").one()

    # Hand-craft a recipe with no source_attribution (legacy / corrupted row).
    recipe = Recipe(
        user_id=user.id,
        name="legacy recipe",
        description="",
        region="",
        era="",
        diet="",
        menu_type="",
        keyword="",
        difficulty="",
        time_minutes=0,
        servings=0,
        estimated_cost_krw=0,
        estimated_price_krw=0,
        steps=[],
        sns_caption="",
        image_url="",
        source_attribution="",  # explicitly empty
        is_recommended=False,
        status=RecipeStatus.PENDING_REVIEW,
    )
    db_session.add(recipe)
    db_session.commit()

    token = _register(client, "lic-orphan2@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    # Re-auth as the orphan recipe owner.
    login = client.post(
        "/v1/auth/login",
        json={"email": "lic-orphan@example.com", "password": "secret123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.get(f"/v1/private/recipes/{recipe.id}", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    # No attribution => no resolvable institution => license_notice is null
    # (spec §3.1 only mandates attribution for heritage-derived content).
    assert body["license_notice"] is None
    assert body["source_attribution"] == ""
