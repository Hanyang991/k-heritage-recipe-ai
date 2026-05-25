"""Tests for the vector-similarity variant of related-recipe recommendations.

Companion to ``test_recipes_related.py``: the tag-scorer tests there pin
the original behaviour, this file covers the embedding-backed path
that ``RECOMMENDATION_PROVIDER=vector`` (default) switches to.

We exclusively use ``EMBEDDING_PROVIDER=mock`` (set in ``conftest.py``)
so the deterministic hash-based embedder makes ordering reproducible
across runs / processes — see :mod:`app.services.embeddings.mock` for
the L2-normalised vector construction. The mock embedder produces a
different vector for each unique input text, and similar (longer
shared prefix / substring) inputs produce closer vectors only by
coincidence of the hash. We therefore assert on **structural**
behaviours (ranking exists, fallback fires, lazy backfill works)
rather than specific cosine values.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.ingredient import Ingredient, RecipeIngredient
from app.models.recipe import Recipe, RecipeStatus
from app.models.user import User
from app.services.recipe_embeddings import (
    compute_recipe_embedding_text,
    cosine_similarity,
    embed_recipe,
    ensure_recipe_embedding,
    store_recipe_embedding,
)
from app.services.recommendation import find_related_recipes

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
    description: str = "",
    embed: bool = True,
) -> Recipe:
    """Create a recipe + optionally embed it.

    ``embed=False`` simulates a back-catalogue row with
    ``embedding_values=None`` (which the lazy-backfill / fallback paths
    rely on).
    """
    recipe = Recipe(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=name,
        description=description,
        keyword=keyword,
        region=region,
        era=era,
        diet=diet,
        menu_type=menu_type,
        status=status,
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
    if embed:
        store_recipe_embedding(db, recipe)
    db.flush()
    return recipe


def _register(client: TestClient, email: str) -> str:
    r = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "secret123"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


# ---------- compute_recipe_embedding_text -----------------------------------


def test_embedding_text_includes_all_filled_fields(db_session: Session) -> None:
    user = User(email="t1@example.com", hashed_password="x", display_name="t1")
    db_session.add(user)
    db_session.flush()
    recipe = _make_recipe(
        db_session,
        user.id,
        name="쑥 라떼",
        keyword="쑥",
        region="전라북도",
        era="조선",
        diet="비건",
        menu_type="디저트 음료",
        ingredients=["쑥", "두유"],
        description="봄철 디저트 음료",
        embed=False,
    )
    text = compute_recipe_embedding_text(recipe)
    for needle in [
        "쑥 라떼",
        "키워드: 쑥",
        "메뉴유형: 디저트 음료",
        "지역: 전라북도",
        "시대: 조선",
        "식단: 비건",
        "재료: 쑥, 두유",
        "설명: 봄철 디저트 음료",
    ]:
        assert needle in text, (needle, text)


def test_embedding_text_omits_empty_fields(db_session: Session) -> None:
    user = User(email="t2@example.com", hashed_password="x", display_name="t2")
    db_session.add(user)
    db_session.flush()
    recipe = _make_recipe(
        db_session,
        user.id,
        name="ingredient only",
        ingredients=["쌀"],
        embed=False,
    )
    text = compute_recipe_embedding_text(recipe)
    assert "키워드:" not in text
    assert "지역:" not in text
    assert "재료: 쌀" in text


def test_embedding_text_is_deterministic(db_session: Session) -> None:
    user = User(email="t3@example.com", hashed_password="x", display_name="t3")
    db_session.add(user)
    db_session.flush()
    a = _make_recipe(db_session, user.id, name="r", keyword="쑥", ingredients=["쌀"], embed=False)
    b = _make_recipe(
        db_session,
        user.id,
        name="r",
        keyword="쑥",
        ingredients=["쌀"],
        embed=False,
    )
    assert compute_recipe_embedding_text(a) == compute_recipe_embedding_text(b)


# ---------- embed_recipe / store_recipe_embedding ---------------------------


def test_embed_recipe_returns_normalised_vector(db_session: Session) -> None:
    user = User(email="t4@example.com", hashed_password="x", display_name="t4")
    db_session.add(user)
    db_session.flush()
    recipe = _make_recipe(
        db_session, user.id, name="r", keyword="쑥", ingredients=["쌀"], embed=False
    )
    vector = embed_recipe(recipe)
    # Mock embedder defaults to 768 dimensions.
    assert len(vector) == 768
    # L2 norm should be ~1 (allow floating-point slack).
    norm_sq = sum(x * x for x in vector)
    assert 0.99 <= norm_sq <= 1.01


def test_store_recipe_embedding_persists(db_session: Session) -> None:
    user = User(email="t5@example.com", hashed_password="x", display_name="t5")
    db_session.add(user)
    db_session.flush()
    recipe = _make_recipe(
        db_session, user.id, name="r", keyword="쑥", ingredients=["쌀"], embed=False
    )
    assert recipe.embedding_values is None
    store_recipe_embedding(db_session, recipe)
    db_session.flush()
    assert recipe.embedding_values is not None
    assert len(recipe.embedding_values) == 768


def test_ensure_recipe_embedding_is_cached(db_session: Session) -> None:
    """Second call must reuse the stored vector instead of re-embedding."""
    user = User(email="t6@example.com", hashed_password="x", display_name="t6")
    db_session.add(user)
    db_session.flush()
    recipe = _make_recipe(
        db_session, user.id, name="r", keyword="쑥", ingredients=["쌀"], embed=False
    )
    first = ensure_recipe_embedding(db_session, recipe)
    second = ensure_recipe_embedding(db_session, recipe)
    assert first == second
    assert recipe.embedding_values == first


# ---------- cosine_similarity ----------------------------------------------


def test_cosine_similarity_self_match_is_one() -> None:
    v = [0.6, 0.8]  # unit norm
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_empty_returns_zero() -> None:
    assert cosine_similarity([], [1.0, 0.0]) == 0.0
    assert cosine_similarity([1.0], []) == 0.0


def test_cosine_similarity_mismatched_dim_returns_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


# ---------- find_related_recipes vector path --------------------------------


def test_vector_path_returns_embedded_candidates(db_session: Session) -> None:
    """Embedded candidates are eligible for vector ranking.

    The mock hash-based embedder produces vectors whose pairwise cosine
    can occasionally land slightly below zero (uncorrelated hashes →
    expected cosine ~0). Such candidates are dropped by the ``score <=
    0`` filter — same behaviour as production with a real embedder
    when text is genuinely unrelated. We therefore only assert that
    **some** of the candidates surface and that every returned score
    is strictly positive.
    """
    viewer = User(email="vp1@example.com", hashed_password="x", display_name="vp1")
    db_session.add(viewer)
    db_session.flush()

    seed = _make_recipe(db_session, viewer.id, name="seed", keyword="쑥", ingredients=["쌀"])
    candidate_names = {f"candidate-{i}" for i in range(5)}
    for cname in candidate_names:
        _make_recipe(db_session, viewer.id, name=cname, keyword="쑥", ingredients=["쌀"])
    db_session.commit()

    results = find_related_recipes(
        db_session, seed=seed, viewer=viewer, limit=10, provider="vector"
    )
    names = {rec.recipe.name for rec in results}
    assert names & candidate_names, "expected at least one embedded candidate to rank"
    for rec in results:
        assert 0.0 < rec.match_score <= 1.0


def test_vector_path_skips_candidates_without_embedding(db_session: Session) -> None:
    """A NULL embedding candidate is excluded from vector ranking.

    We make the embedded candidate's text identical to the seed so the
    mock embedder gives them cosine == 1, guaranteeing at least one
    positive hit and stopping ``find_related_recipes`` from falling
    through to the tag scorer (where the unembedded candidate would
    leak in via shared keyword).
    """
    viewer = User(email="vp2@example.com", hashed_password="x", display_name="vp2")
    db_session.add(viewer)
    db_session.flush()

    seed = _make_recipe(db_session, viewer.id, name="twin", keyword="쑥", ingredients=["쌀"])
    _make_recipe(
        db_session,
        viewer.id,
        name="twin",
        keyword="쑥",
        ingredients=["쌀"],
        embed=True,
    )
    _make_recipe(
        db_session,
        viewer.id,
        name="unembedded",
        keyword="쑥",
        ingredients=["쌀"],
        embed=False,
    )
    db_session.commit()

    results = find_related_recipes(
        db_session, seed=seed, viewer=viewer, limit=10, provider="vector"
    )
    names = {rec.recipe.name for rec in results}
    assert "twin" in names
    assert "unembedded" not in names


def test_vector_path_falls_back_to_tag_when_no_embeddings(db_session: Session) -> None:
    """No candidate has an embedding → vector returns empty → tag scorer fires."""
    viewer = User(email="vp3@example.com", hashed_password="x", display_name="vp3")
    db_session.add(viewer)
    db_session.flush()

    seed = _make_recipe(db_session, viewer.id, name="seed", keyword="쑥", embed=False)
    # All candidates skip embedding to force the fallback path.
    _make_recipe(db_session, viewer.id, name="cand-1", keyword="쑥", embed=False)
    _make_recipe(db_session, viewer.id, name="cand-2", keyword="쑥", embed=False)
    db_session.commit()

    results = find_related_recipes(
        db_session, seed=seed, viewer=viewer, limit=10, provider="vector"
    )
    # Tag scorer fired: shared keyword scores >= WEIGHT_KEYWORD.
    assert results, "vector path should fall back to tag scorer"
    names = {rec.recipe.name for rec in results}
    assert {"cand-1", "cand-2"} <= names


def test_vector_path_respects_visibility(db_session: Session) -> None:
    """Other users' pending recipes must not leak via vector ranking either."""
    viewer = User(email="vp4@example.com", hashed_password="x", display_name="vp4")
    other = User(email="vp4-other@example.com", hashed_password="x", display_name="o")
    db_session.add_all([viewer, other])
    db_session.flush()

    seed = _make_recipe(db_session, viewer.id, name="seed", keyword="쑥")
    _make_recipe(
        db_session,
        other.id,
        name="hidden-pending",
        keyword="쑥",
        status=RecipeStatus.PENDING_REVIEW,
    )
    visible = _make_recipe(
        db_session,
        other.id,
        name="visible-approved",
        keyword="쑥",
        status=RecipeStatus.APPROVED,
    )
    db_session.commit()

    results = find_related_recipes(
        db_session, seed=seed, viewer=viewer, limit=10, provider="vector"
    )
    names = {rec.recipe.name for rec in results}
    assert "hidden-pending" not in names
    assert visible.name in names


def test_vector_path_orders_by_cosine_desc(db_session: Session) -> None:
    """Output scores must be monotonically non-increasing."""
    viewer = User(email="vp5@example.com", hashed_password="x", display_name="vp5")
    db_session.add(viewer)
    db_session.flush()

    seed = _make_recipe(db_session, viewer.id, name="seed", keyword="쑥", ingredients=["쌀"])
    for i in range(5):
        _make_recipe(
            db_session,
            viewer.id,
            name=f"r-{i}",
            keyword=f"k{i}",
            ingredients=[f"ing-{i}"],
        )
    db_session.commit()

    results = find_related_recipes(
        db_session, seed=seed, viewer=viewer, limit=10, provider="vector"
    )
    scores = [rec.match_score for rec in results]
    assert scores == sorted(scores, reverse=True)


def test_provider_dispatch_via_settings(db_session: Session, monkeypatch) -> None:
    """``RECOMMENDATION_PROVIDER=tag`` forces the tag scorer even when embeddings exist."""
    settings = get_settings()
    monkeypatch.setattr(settings, "recommendation_provider", "tag")

    viewer = User(email="dispatch@example.com", hashed_password="x", display_name="d")
    db_session.add(viewer)
    db_session.flush()

    seed = _make_recipe(db_session, viewer.id, name="seed", keyword="쑥", ingredients=["쌀"])
    _make_recipe(db_session, viewer.id, name="tag-match", keyword="쑥")
    db_session.commit()

    results = find_related_recipes(db_session, seed=seed, viewer=viewer, limit=10)
    # Tag scorer awarded WEIGHT_KEYWORD == 1.0 → match_score should equal that.
    assert results
    assert results[0].match_score == pytest.approx(1.0)


# ---------- endpoint integration --------------------------------------------


def test_related_endpoint_vector_path_happy(client: TestClient) -> None:
    """End-to-end: generate two recipes (auto-embedded by the hook), call /related."""
    token = _register(client, "vector-endpoint@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Two generate calls so the user owns multiple recipes that the
    # related endpoint can rank against each other.
    r1 = client.post(
        "/v1/private/recipes/generate",
        headers=headers,
        json={"keyword": "쑥", "region": "전라북도", "diet": "비건", "menu_type": "디저트 음료"},
    )
    assert r1.status_code == 200, r1.text
    r2 = client.post(
        "/v1/private/recipes/generate",
        headers=headers,
        json={"keyword": "오미자", "region": "전라북도", "diet": "비건", "menu_type": "음료"},
    )
    assert r2.status_code == 200, r2.text

    # Pick the first candidate from the first call as the seed.
    seed_id = r1.json()["candidates"][0]["id"]
    related = client.get(
        f"/v1/private/recipes/{seed_id}/related",
        headers=headers,
    )
    assert related.status_code == 200, related.text
    payload = related.json()
    assert isinstance(payload, list)
    # The hook embedded every newly-generated recipe, so the vector
    # path should find at least one candidate.
    assert len(payload) >= 1
    # Match scores are cosine in (0, 1] when L2-normalised vectors.
    for entry in payload:
        assert 0.0 < entry["match_score"] <= 1.0
    # Same response shape as the tag-path endpoint (RelatedRecipeOut).
    first = payload[0]
    for key in (
        "id",
        "name",
        "region",
        "era",
        "diet",
        "menu_type",
        "keyword",
        "status",
        "is_recommended",
        "image_url",
        "estimated_cost_krw",
        "time_minutes",
        "match_score",
    ):
        assert key in first, key


def test_related_endpoint_limit_still_clamps(client: TestClient) -> None:
    """Vector path must honour ``limit`` the same as the tag path."""
    token = _register(client, "vector-limit@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    for _ in range(3):
        client.post(
            "/v1/private/recipes/generate",
            headers=headers,
            json={
                "keyword": "쑥",
                "region": "전라북도",
                "diet": "비건",
                "menu_type": "디저트 음료",
            },
        )
    # Pull a seed id from listing.
    listing = client.get("/v1/private/recipes", headers=headers)
    assert listing.status_code == 200, listing.text
    rows = listing.json()
    assert rows, listing.text
    seed_id = rows[0]["id"]

    response = client.get(
        f"/v1/private/recipes/{seed_id}/related?limit=2",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert len(response.json()) <= 2


# ---------- backfill job ----------------------------------------------------


def test_backfill_recipe_embeddings_walks_unembedded_rows(db_session: Session) -> None:
    from app.jobs.backfill_recipe_embeddings import run_recipe_embedding_backfill

    user = User(email="bf@example.com", hashed_password="x", display_name="bf")
    db_session.add(user)
    db_session.flush()

    # Mix embedded + unembedded — backfill should only touch the latter.
    _make_recipe(db_session, user.id, name="already-embedded", keyword="x")
    _make_recipe(db_session, user.id, name="back-catalogue-1", keyword="y", embed=False)
    _make_recipe(db_session, user.id, name="back-catalogue-2", keyword="z", embed=False)
    db_session.commit()

    report = run_recipe_embedding_backfill(session=db_session, batch_size=10)
    assert report.scanned == 3
    assert report.embedded == 2
    assert report.skipped_already_embedded == 1
    assert report.failures == 0

    # Confirm both back-catalogue rows now have embeddings.
    db_session.expire_all()
    for name in ("back-catalogue-1", "back-catalogue-2"):
        row = db_session.query(Recipe).filter(Recipe.name == name).one()
        assert row.embedding_values is not None


def test_backfill_force_re_embeds(db_session: Session) -> None:
    from app.jobs.backfill_recipe_embeddings import run_recipe_embedding_backfill

    user = User(email="bf2@example.com", hashed_password="x", display_name="bf2")
    db_session.add(user)
    db_session.flush()

    _make_recipe(db_session, user.id, name="one", keyword="x")
    _make_recipe(db_session, user.id, name="two", keyword="y")
    db_session.commit()

    report = run_recipe_embedding_backfill(session=db_session, batch_size=10, force=True)
    assert report.scanned == 2
    assert report.embedded == 2
    assert report.skipped_already_embedded == 0
