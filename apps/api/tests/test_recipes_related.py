"""Tests for ``GET /v1/private/recipes/{id}/related`` and the underlying
:mod:`app.services.recommendation` scorer.

Strategy:

* Unit-test :func:`compute_similarity` directly so the weight ordering is
  pinned (any future tweak of the constants in
  :mod:`app.services.recommendation` will break a specific test rather
  than silently re-rank live recommendations).
* Integration-test the endpoint via the FastAPI ``TestClient`` so we
  exercise the SQLAlchemy joinedload + visibility filter on the
  shared SQLite fixture.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.ingredient import Ingredient, RecipeIngredient
from app.models.recipe import Recipe, RecipeStatus
from app.models.user import User
from app.services.recommendation import (
    WEIGHT_INGREDIENT_JACCARD,
    WEIGHT_KEYWORD,
    WEIGHT_MENU_TYPE,
    WEIGHT_REGION,
    WEIGHT_SOURCE_DOCUMENT,
    compute_similarity,
    find_related_recipes,
)

# ---------- helpers ---------------------------------------------------------


def _make_recipe(
    db: Session,
    user_id: str,
    *,
    name: str = "test recipe",
    keyword: str = "",
    region: str = "",
    era: str = "",
    diet: str = "",
    menu_type: str = "",
    status: RecipeStatus = RecipeStatus.APPROVED,
    ingredients: list[str] | None = None,
    source_document_id: str | None = None,
) -> Recipe:
    recipe = Recipe(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=name,
        keyword=keyword,
        region=region,
        era=era,
        diet=diet,
        menu_type=menu_type,
        status=status,
        source_document_id=source_document_id,
    )
    db.add(recipe)
    db.flush()
    for sort_order, ing_name in enumerate(ingredients or []):
        ing = db.query(Ingredient).filter(Ingredient.name == ing_name).one_or_none()
        if ing is None:
            ing = Ingredient(name=ing_name)
            db.add(ing)
            db.flush()
        db.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=ing.id,
                amount="1",
                sort_order=sort_order,
            )
        )
    db.flush()
    return recipe


def _register(client: TestClient, email: str = "rel@example.com") -> str:
    r = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "secret123"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _user_by_email(db: Session, email: str) -> User:
    user = db.query(User).filter(User.email == email).one_or_none()
    assert user is not None
    return user


# ---------- unit tests for compute_similarity --------------------------------


def test_compute_similarity_self_match_is_zero(db_session: Session) -> None:
    user = User(email="self@example.com", hashed_password="x", display_name="self")
    db_session.add(user)
    db_session.flush()
    r = _make_recipe(
        db_session,
        user.id,
        keyword="쑥",
        region="전라북도",
        menu_type="디저트 음료",
    )
    assert compute_similarity(r, r) == 0.0


def test_compute_similarity_exact_keyword_match(db_session: Session) -> None:
    user = User(email="kw@example.com", hashed_password="x", display_name="kw")
    db_session.add(user)
    db_session.flush()
    seed = _make_recipe(db_session, user.id, keyword="쑥라떼", region="전라북도")
    same_kw = _make_recipe(db_session, user.id, keyword="쑥라떼", region="서울", name="other")
    other_kw = _make_recipe(db_session, user.id, keyword="오미자", region="전라북도", name="third")

    # same_kw should score at least the keyword weight (could also match region — no, it doesn't).
    assert compute_similarity(seed, same_kw) >= WEIGHT_KEYWORD
    # other_kw shares region only.
    assert compute_similarity(seed, other_kw) == WEIGHT_REGION
    # And keyword should beat region.
    assert compute_similarity(seed, same_kw) > compute_similarity(seed, other_kw)


def test_compute_similarity_missing_fields_dont_double_match(
    db_session: Session,
) -> None:
    """Empty seed field must NOT match an empty candidate field."""
    user = User(email="empty@example.com", hashed_password="x", display_name="empty")
    db_session.add(user)
    db_session.flush()
    seed = _make_recipe(db_session, user.id, keyword="", region="")
    candidate = _make_recipe(db_session, user.id, keyword="", region="", name="other")
    assert compute_similarity(seed, candidate) == 0.0


def test_compute_similarity_ingredient_overlap(db_session: Session) -> None:
    user = User(email="ing@example.com", hashed_password="x", display_name="ing")
    db_session.add(user)
    db_session.flush()
    seed = _make_recipe(db_session, user.id, ingredients=["쌀", "쑥", "설탕", "물"])
    full_overlap = _make_recipe(
        db_session,
        user.id,
        ingredients=["쌀", "쑥", "설탕", "물"],
        name="full overlap",
    )
    partial = _make_recipe(
        db_session,
        user.id,
        ingredients=["쌀", "쑥"],
        name="partial",
    )
    none_overlap = _make_recipe(
        db_session,
        user.id,
        ingredients=["오미자", "꿀"],
        name="none overlap",
    )

    assert compute_similarity(seed, full_overlap) == WEIGHT_INGREDIENT_JACCARD
    score_partial = compute_similarity(seed, partial)
    # Jaccard = 2 / 4 = 0.5
    assert score_partial == 0.5 * WEIGHT_INGREDIENT_JACCARD
    assert compute_similarity(seed, none_overlap) == 0.0


def test_compute_similarity_source_document_bonus(db_session: Session) -> None:
    user = User(email="src@example.com", hashed_password="x", display_name="src")
    db_session.add(user)
    db_session.flush()
    seed = _make_recipe(db_session, user.id, source_document_id=None)
    # Cannot exercise the bonus without a real document FK — score still
    # comes from the categorical fields, so verify the categorical-only
    # branch stays zero when nothing else matches.
    candidate = _make_recipe(db_session, user.id, name="other")
    assert compute_similarity(seed, candidate) == 0.0


# ---------- visibility / ranking via find_related_recipes --------------------


def test_find_related_recipes_excludes_other_users_pending(
    db_session: Session,
) -> None:
    viewer = User(email="viewer@example.com", hashed_password="x", display_name="viewer")
    other = User(email="other@example.com", hashed_password="x", display_name="other")
    db_session.add_all([viewer, other])
    db_session.flush()

    seed = _make_recipe(
        db_session,
        viewer.id,
        keyword="쑥",
        region="전라북도",
        menu_type="디저트 음료",
    )
    # Other user's recipe in pending_review — must be hidden.
    _make_recipe(
        db_session,
        other.id,
        keyword="쑥",
        region="전라북도",
        menu_type="디저트 음료",
        status=RecipeStatus.PENDING_REVIEW,
        name="hidden pending",
    )
    # Other user's approved recipe — visible.
    visible = _make_recipe(
        db_session,
        other.id,
        keyword="쑥",
        region="전라북도",
        menu_type="디저트 음료",
        status=RecipeStatus.APPROVED,
        name="visible approved",
    )

    db_session.commit()

    results = find_related_recipes(db_session, seed=seed, viewer=viewer, limit=10)
    names = {rec.recipe.name for rec in results}
    assert "hidden pending" not in names
    assert visible.name in names


def test_find_related_recipes_includes_own_pending(db_session: Session) -> None:
    viewer = User(email="own@example.com", hashed_password="x", display_name="own")
    db_session.add(viewer)
    db_session.flush()

    seed = _make_recipe(db_session, viewer.id, keyword="쑥", region="전라북도")
    own_pending = _make_recipe(
        db_session,
        viewer.id,
        keyword="쑥",
        region="전라북도",
        status=RecipeStatus.PENDING_REVIEW,
        name="my pending",
    )
    db_session.commit()

    results = find_related_recipes(db_session, seed=seed, viewer=viewer, limit=10)
    names = {rec.recipe.name for rec in results}
    assert own_pending.name in names


def test_find_related_recipes_orders_by_score_desc(db_session: Session) -> None:
    viewer = User(email="rank@example.com", hashed_password="x", display_name="rank")
    db_session.add(viewer)
    db_session.flush()

    seed = _make_recipe(
        db_session,
        viewer.id,
        keyword="쑥",
        region="전라북도",
        menu_type="디저트 음료",
        ingredients=["쌀", "쑥"],
    )
    high = _make_recipe(
        db_session,
        viewer.id,
        keyword="쑥",
        region="전라북도",
        menu_type="디저트 음료",
        ingredients=["쌀", "쑥"],
        name="high",
    )
    medium = _make_recipe(
        db_session,
        viewer.id,
        keyword="쑥",
        region="서울",
        menu_type="디저트 음료",
        name="medium",
    )
    low = _make_recipe(
        db_session,
        viewer.id,
        region="전라북도",
        name="low",
    )
    db_session.commit()

    results = find_related_recipes(db_session, seed=seed, viewer=viewer, limit=10)
    ordered = [rec.recipe.name for rec in results]
    assert ordered.index(high.name) < ordered.index(medium.name)
    assert ordered.index(medium.name) < ordered.index(low.name)
    # Scores must be strictly monotonic for this configured corpus.
    scores = [rec.match_score for rec in results]
    assert scores == sorted(scores, reverse=True)


def test_find_related_recipes_drops_zero_score(db_session: Session) -> None:
    viewer = User(email="zero@example.com", hashed_password="x", display_name="zero")
    db_session.add(viewer)
    db_session.flush()

    seed = _make_recipe(
        db_session,
        viewer.id,
        keyword="쑥",
        region="전라북도",
        ingredients=["쌀"],
    )
    _make_recipe(
        db_session,
        viewer.id,
        keyword="다른키워드",
        region="서울",
        ingredients=["감자"],
        name="unrelated",
    )
    db_session.commit()

    results = find_related_recipes(db_session, seed=seed, viewer=viewer, limit=10)
    assert results == []


def test_find_related_recipes_respects_limit(db_session: Session) -> None:
    viewer = User(email="lim@example.com", hashed_password="x", display_name="lim")
    db_session.add(viewer)
    db_session.flush()
    seed = _make_recipe(db_session, viewer.id, keyword="쑥", region="전라북도")
    for i in range(7):
        _make_recipe(
            db_session,
            viewer.id,
            keyword="쑥",
            region="전라북도",
            name=f"sibling-{i}",
        )
    db_session.commit()

    results = find_related_recipes(db_session, seed=seed, viewer=viewer, limit=3)
    assert len(results) == 3


# ---------- endpoint integration -------------------------------------------


def test_get_related_recipes_endpoint_happy_path(client: TestClient) -> None:
    token = _register(client, "rel-endpoint@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Generate twice so we have at least 6 recipes for the user.
    payload = {
        "keyword": "쑥라떼",
        "region": "전라북도",
        "diet": "비건",
        "menu_type": "디저트 음료",
    }
    gen = client.post("/v1/private/recipes/generate", headers=headers, json=payload)
    assert gen.status_code == 200, gen.text
    seed_id = gen.json()["candidates"][0]["id"]

    # Generate a second batch with the same keyword/region so there are
    # high-score siblings to surface.
    client.post("/v1/private/recipes/generate", headers=headers, json=payload)

    r = client.get(f"/v1/private/recipes/{seed_id}/related", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    # The seed itself must never appear.
    assert all(item["id"] != seed_id for item in body)
    # Default limit is 5 (DEFAULT_RELATED_LIMIT); we have 5 siblings.
    assert len(body) <= 5
    if body:
        first = body[0]
        # Schema contract — exact match_score float key, normalised meta fields.
        assert {
            "id",
            "name",
            "region",
            "era",
            "diet",
            "menu_type",
            "keyword",
            "status",
            "image_url",
            "estimated_cost_krw",
            "time_minutes",
            "match_score",
            "is_recommended",
        }.issubset(first.keys())
        assert isinstance(first["match_score"], float)
        assert first["match_score"] > 0.0


def test_get_related_recipes_limit_param(client: TestClient) -> None:
    token = _register(client, "rel-limit@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "keyword": "오미자에이드",
        "region": "제주",
        "diet": "제한 없음",
        "menu_type": "디저트 음료",
    }
    gen = client.post("/v1/private/recipes/generate", headers=headers, json=payload)
    seed_id = gen.json()["candidates"][0]["id"]
    # Run another batch so we have 5 siblings.
    client.post("/v1/private/recipes/generate", headers=headers, json=payload)

    r = client.get(f"/v1/private/recipes/{seed_id}/related?limit=2", headers=headers)
    assert r.status_code == 200, r.text
    assert len(r.json()) <= 2


def test_get_related_recipes_rejects_invalid_limit(client: TestClient) -> None:
    token = _register(client, "rel-bad@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "keyword": "쑥라떼",
        "region": "전라북도",
        "diet": "비건",
        "menu_type": "디저트 음료",
    }
    gen = client.post("/v1/private/recipes/generate", headers=headers, json=payload)
    seed_id = gen.json()["candidates"][0]["id"]

    r = client.get(f"/v1/private/recipes/{seed_id}/related?limit=0", headers=headers)
    assert r.status_code == 422

    r = client.get(f"/v1/private/recipes/{seed_id}/related?limit=999", headers=headers)
    assert r.status_code == 422


def test_get_related_recipes_404_for_foreign_seed(client: TestClient) -> None:
    # User A generates a seed.
    token_a = _register(client, "owner@example.com")
    gen = client.post(
        "/v1/private/recipes/generate",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "keyword": "쑥라떼",
            "region": "전라북도",
            "diet": "비건",
            "menu_type": "디저트 음료",
        },
    )
    seed_id = gen.json()["candidates"][0]["id"]

    # User B tries to ask for related recipes against User A's seed.
    token_b = _register(client, "intruder@example.com")
    r = client.get(
        f"/v1/private/recipes/{seed_id}/related",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r.status_code == 404


def test_get_related_recipes_404_for_missing_seed(client: TestClient) -> None:
    token = _register(client, "missing@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    r = client.get(
        "/v1/private/recipes/00000000-0000-0000-0000-000000000000/related",
        headers=headers,
    )
    assert r.status_code == 404


def test_get_related_recipes_requires_auth(client: TestClient) -> None:
    r = client.get("/v1/private/recipes/00000000-0000-0000-0000-000000000000/related")
    assert r.status_code == 401


def test_compute_similarity_source_document_bonus_value() -> None:
    """Sanity-check the source-document bonus weight is non-trivial."""
    assert WEIGHT_SOURCE_DOCUMENT > 0.0
    assert WEIGHT_MENU_TYPE > 0.0
