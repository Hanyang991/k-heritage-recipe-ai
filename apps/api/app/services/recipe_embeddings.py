"""Recipe-embedding service — text payload + storage helpers.

Vector variant of the related-recipes feature (todo §1.4). The tag
scorer in :mod:`app.services.recommendation` is preserved and remains
available behind ``RECOMMENDATION_PROVIDER=tag``; this module builds
the embedding-backed pipeline that the default
``RECOMMENDATION_PROVIDER=vector`` setting hands queries to.

Design choices:

* **Embed once per write.** New recipes are embedded synchronously in
  the ``/generate`` hook after the row is committed (recipe generation
  already takes ~30 s end-to-end via the LLM, so an extra
  Mock/Gemini embedding call is a rounding error). Updates that touch
  any field used by :func:`compute_recipe_embedding_text` re-embed.
* **Lazy backfill.** Recipes generated before this feature shipped
  have ``embedding_values=NULL``. The query-time path calls
  :func:`ensure_recipe_embedding` on the seed (and skips candidates
  that still lack an embedding) so the panel keeps working before
  ``backfill_recipe_embeddings`` finishes the back catalogue.
* **L2-normalised vectors.** Both ``MockEmbeddingAdapter`` and Gemini
  ``text-embedding-004`` return unit-norm vectors at the project's
  default ``output_dimensionality=768``, so cosine similarity == dot
  product. We rely on that contract in :func:`cosine_similarity` to
  keep the inner loop allocation-free.
* **Single text representation per recipe.** Cooking-style descriptors
  (region / era / diet / menu_type / keyword) and the ingredient list
  carry the strongest semantic signal — the LLM produces highly
  uniform ``description`` and ``steps`` text that would otherwise
  drown the signal in boilerplate. The format is stable so changing
  it requires a re-embed for every existing recipe (call
  ``backfill_recipe_embeddings(force=True)`` after a change).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable

from sqlalchemy.orm import Session, joinedload

from app.models.ingredient import RecipeIngredient
from app.models.recipe import Recipe
from app.services.embeddings import get_embedding_adapter

logger = logging.getLogger(__name__)


def compute_recipe_embedding_text(recipe: Recipe) -> str:
    """Build the canonical text representation embedded for ``recipe``.

    The format is deterministic so two processes with the same adapter
    settings produce the same vector for the same recipe. Format is:

        <name> | 키워드: <keyword> | 메뉴유형: <menu_type> |
        지역: <region> | 시대: <era> | 식단: <diet> |
        재료: <ingredient1>, <ingredient2>, ... | 설명: <description>

    Ingredients are sorted by ``sort_order`` so two recipes with the
    same ingredient set in the same display order get the same text
    even when the underlying ``RecipeIngredient`` rows were inserted
    out of order.

    Empty fields are dropped (no ``설명: `` with empty value) so the
    embedder doesn't waste capacity learning the project's punctuation
    style.
    """
    parts: list[str] = []
    if recipe.name:
        parts.append(recipe.name.strip())

    field_labels: list[tuple[str, str]] = [
        ("키워드", recipe.keyword),
        ("메뉴유형", recipe.menu_type),
        ("지역", recipe.region),
        ("시대", recipe.era),
        ("식단", recipe.diet),
    ]
    for label, value in field_labels:
        v = (value or "").strip()
        if v:
            parts.append(f"{label}: {v}")

    ingredient_names = _ordered_ingredient_names(recipe)
    if ingredient_names:
        parts.append("재료: " + ", ".join(ingredient_names))

    description = (recipe.description or "").strip()
    if description:
        parts.append(f"설명: {description}")

    return " | ".join(parts)


def _ordered_ingredient_names(recipe: Recipe) -> list[str]:
    """Stable-sorted ingredient names for the embedding payload."""
    lines = list(recipe.ingredients or [])
    # ``RecipeIngredient`` has a composite (recipe_id, ingredient_id)
    # primary key, no scalar ``id`` column. Fall back to ``ingredient_id``
    # as the secondary sort key so two lines with the same ``sort_order``
    # still produce deterministic output.
    lines.sort(
        key=lambda line: (
            getattr(line, "sort_order", 0) or 0,
            getattr(line, "ingredient_id", "") or "",
        )
    )
    names: list[str] = []
    for line in lines:
        ing = getattr(line, "ingredient", None)
        name = getattr(ing, "name", "") if ing is not None else ""
        normalised = (name or "").strip()
        if normalised:
            names.append(normalised)
    return names


def embed_text(text: str) -> list[float]:
    """Embed a single string through the configured provider.

    Empty input is short-circuited to an empty list (zero-length
    vector). The recommendation service treats a zero-length embedding
    as "no embedding yet" and skips that recipe from vector ranking —
    matching the contract for rows with ``embedding_values=NULL`` in
    the DB.
    """
    text = (text or "").strip()
    if not text:
        return []
    adapter = get_embedding_adapter()
    result = adapter.embed([text])
    if not result:
        return []
    return list(result[0].values)


def embed_recipe(recipe: Recipe) -> list[float]:
    """Compute and return the embedding for ``recipe`` without persisting.

    Caller is responsible for assigning the returned value to
    ``recipe.embedding_values`` and committing. Split from
    :func:`store_recipe_embedding` so unit tests can assert the vector
    contents without touching the DB session.
    """
    text = compute_recipe_embedding_text(recipe)
    return embed_text(text)


def store_recipe_embedding(db: Session, recipe: Recipe) -> list[float]:
    """Embed ``recipe`` and persist the vector on the row.

    Returns the freshly-computed vector. Does NOT commit — the caller
    decides when to flush so this can be batched into the same
    transaction as recipe creation.

    If the embedding adapter raises (live Gemini / Vertex transient
    failure), the exception is swallowed and the recipe is left with
    ``embedding_values=None``. The vector-path scorer will then treat
    the row as ineligible (skipping it as a candidate) and the seed
    falls back to the tag scorer when needed — i.e. embedding failure
    degrades gracefully rather than breaking recipe creation.
    """
    try:
        values = embed_recipe(recipe)
    except Exception:  # pragma: no cover - defensive logging path
        logger.exception(
            "store_recipe_embedding: embedding failed for recipe %s; leaving embedding_values=None",
            recipe.id,
        )
        return []
    recipe.embedding_values = values if values else None
    return values


def ensure_recipe_embedding(db: Session, recipe: Recipe) -> list[float]:
    """Return the stored embedding for ``recipe`` or compute + persist one.

    Used by :func:`app.services.recommendation.find_related_recipes` so
    a seed recipe predating this feature still produces vector-ranked
    related cards on the first request. Subsequent requests reuse the
    persisted value.
    """
    if recipe.embedding_values:
        return list(recipe.embedding_values)
    values = store_recipe_embedding(db, recipe)
    if values:
        db.add(recipe)
        db.flush()
    return values


def load_recipe_with_ingredients(db: Session, recipe_id: str) -> Recipe | None:
    """Fetch a recipe + its ingredients in one round-trip.

    Helper used by the backfill job and the lazy-backfill path so the
    embedding-text formatter doesn't trigger a lazy-load on every
    candidate.
    """
    return (
        db.query(Recipe)
        .options(joinedload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient))
        .filter(Recipe.id == recipe_id)
        .one_or_none()
    )


def cosine_similarity(a: Iterable[float], b: Iterable[float]) -> float:
    """Cosine similarity between two vectors.

    Both providers (mock + Gemini text-embedding-004 + Vertex
    text-embedding-005) return L2-normalised vectors, so this is
    equivalent to the dot product. We still divide by the norms
    defensively in case a future provider drops the normalisation
    contract or the caller passes a hand-rolled vector.

    Returns 0.0 when either input is empty or has zero norm — the
    recommendation service treats a 0.0 score the same as "no signal"
    and drops the candidate from the results.
    """
    a_list = list(a)
    b_list = list(b)
    if not a_list or not b_list:
        return 0.0
    if len(a_list) != len(b_list):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a_list, b_list, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
