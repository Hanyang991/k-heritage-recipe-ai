"""Related-recipe recommendation service (todo §1.4 "관련 레시피 추천").

Two scorers are available behind the single public entry point
:func:`find_related_recipes`:

* **vector** (default) — cosine similarity over Gemini / Vertex /
  mock embeddings stored on ``recipes.embedding_values``. Uses the
  existing ``app.services.embeddings`` adapter so swapping providers
  (mock → Gemini → Vertex) is a settings change rather than a code
  change. The seed and every eligible candidate are run through
  :func:`app.services.recipe_embeddings.cosine_similarity`. Score
  range is ``(-1, 1]`` for L2-normalised vectors, but in practice we
  drop everything <= 0 so the panel never surfaces unrelated content.
* **tag** — categorical exact-match weights + ingredient Jaccard
  scorer originally shipped in PR #46. Kept available behind
  ``RECOMMENDATION_PROVIDER=tag`` for A/B comparison, smoke testing,
  and as a graceful fallback when the seed has no stored embedding
  yet (e.g. recipes generated before this feature shipped).

The public function signature does not change between providers: the
router and the response model only know about ``RecipeRecommendation``
records. Visibility / ordering / limit semantics are identical.

Why keep both? The user-recipe corpus is small at MVP scale
(per-user O(N), platform-wide O(N×M)) so the tag scorer remains a
useful baseline — it finishes in <50ms cold-cache on SQLite without
any embedding round-trip and produces deterministic scores that play
nicely with the existing pytest fixtures (mock LLM / mock heritage).
For production traffic the vector path is preferred because it
captures soft synonyms ("쑥" / "애엽", "떡" / "경단") that tag matches
cannot, but the tag scorer is the safety net that keeps the panel
useful when an embedding adapter is mid-failure.

Scoring weights are exported as module constants so they're trivially
A/B-able from a future settings module without touching call sites.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.models.ingredient import RecipeIngredient
from app.models.recipe import Recipe, RecipeStatus
from app.models.user import User
from app.services.recipe_embeddings import (
    cosine_similarity,
    ensure_recipe_embedding,
)

logger = logging.getLogger(__name__)

# --- Scoring weights ---------------------------------------------------------
#
# Picked so that an exact-keyword + same-menu_type match (the strongest
# single pairing in the UI) lands around ~1.7, while a recipe that only
# shares a region drifts down to ~0.6 — keeps the cards visibly tiered
# without anyone hitting the 0.0 floor on a real corpus.

WEIGHT_KEYWORD = 1.0
WEIGHT_MENU_TYPE = 0.7
WEIGHT_REGION = 0.6
WEIGHT_DIET = 0.5
WEIGHT_ERA = 0.3
WEIGHT_SOURCE_DOCUMENT = 0.2
# Ingredient overlap is scaled by Jaccard similarity (0..1) so an exact
# ingredient list match scores +1.0, a half-overlap +0.5, etc.
WEIGHT_INGREDIENT_JACCARD = 1.0

DEFAULT_RELATED_LIMIT = 5
MAX_RELATED_LIMIT = 20


@dataclass(slots=True)
class RecipeRecommendation:
    """A single related recipe + the score that ranked it.

    ``match_score`` is monotonic but not normalised to [0, 1] — the upper
    bound depends on which categorical fields the seed has populated.
    Frontends should treat it as a relative ordering signal, not a
    confidence percentage.
    """

    recipe: Recipe
    match_score: float


def _ingredient_name_set(recipe: Recipe) -> set[str]:
    """Return the set of normalised ingredient names attached to ``recipe``.

    SQLAlchemy lazy-loads ``recipe.ingredients`` so callers should make
    sure the seed and every candidate were either loaded inside the same
    session or eager-loaded via ``joinedload`` (this helper assumes the
    latter — see :func:`find_related_recipes`).
    """
    names: set[str] = set()
    for line in recipe.ingredients or []:
        name = getattr(getattr(line, "ingredient", None), "name", "") or ""
        normalised = name.strip().lower()
        if normalised:
            names.add(normalised)
    return names


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def compute_similarity(seed: Recipe, candidate: Recipe) -> float:
    """Score ``candidate`` against ``seed``.

    Pure function — does not touch the DB. ``ingredients`` on both
    arguments are expected to be eagerly loaded.

    The scoring blends:

    * Categorical exact matches on ``keyword`` / ``region`` / ``era`` /
      ``diet`` / ``menu_type``. Each field contributes its weight only
      when **both** the seed and the candidate have a non-empty value
      on that field (so missing-data seeds don't get artificially boosted
      by candidates that also happen to have empty fields).
    * Ingredient Jaccard similarity (case-insensitive on the ingredient
      master name) scaled by :data:`WEIGHT_INGREDIENT_JACCARD`.
    * A small bonus when both recipes were derived from the same
      ``source_document_id`` (heritage doc), which is a strong signal
      that the LLM grounded the two recipes in the same primary text.
    """
    if seed.id == candidate.id:
        return 0.0

    score = 0.0

    def _categorical(seed_val: str, cand_val: str, weight: float) -> float:
        if not seed_val or not cand_val:
            return 0.0
        if seed_val.strip().lower() == cand_val.strip().lower():
            return weight
        return 0.0

    score += _categorical(seed.keyword, candidate.keyword, WEIGHT_KEYWORD)
    score += _categorical(seed.menu_type, candidate.menu_type, WEIGHT_MENU_TYPE)
    score += _categorical(seed.region, candidate.region, WEIGHT_REGION)
    score += _categorical(seed.diet, candidate.diet, WEIGHT_DIET)
    score += _categorical(seed.era, candidate.era, WEIGHT_ERA)

    seed_ings = _ingredient_name_set(seed)
    cand_ings = _ingredient_name_set(candidate)
    score += WEIGHT_INGREDIENT_JACCARD * _jaccard(seed_ings, cand_ings)

    if (
        seed.source_document_id
        and candidate.source_document_id
        and seed.source_document_id == candidate.source_document_id
    ):
        score += WEIGHT_SOURCE_DOCUMENT

    return score


def find_related_recipes(
    db: Session,
    *,
    seed: Recipe,
    viewer: User,
    limit: int = DEFAULT_RELATED_LIMIT,
    provider: str | None = None,
) -> list[RecipeRecommendation]:
    """Return up to ``limit`` recipes ranked by similarity to ``seed``.

    Visibility rules (kept tight on purpose so we never leak in-review
    drafts from other users — this mirrors the existing list endpoint's
    behaviour where every user only sees their own non-public recipes):

    * The viewer's own recipes are eligible regardless of status (so
      drafts and pending-review items show up in the panel for the
      author themselves).
    * Other users' recipes are eligible only when ``status=approved``
      (admin-reviewed for public display).
    * The seed itself is always excluded.

    Provider selection:

    * ``provider`` argument wins when supplied (used by tests and the
      admin A/B endpoint).
    * Otherwise reads :attr:`Settings.recommendation_provider`.
    * ``vector`` runs cosine similarity over stored embeddings; if the
      seed has no embedding yet a one-shot lazy-backfill embeds it,
      and candidates with a NULL embedding are quietly skipped. If
      vector ranking yields zero matches we fall back to the tag
      scorer transparently — the panel never appears empty just
      because the embedding side hasn't caught up.
    * ``tag`` always uses the categorical / Jaccard scorer.

    Candidates with a final score of ``0.0`` are dropped — there is no
    point surfacing a "related" recipe that shares nothing with the
    seed. Ties are broken by ``created_at DESC`` so freshly-generated
    recipes float over older ones.
    """
    if limit <= 0:
        return []
    limit = min(limit, MAX_RELATED_LIMIT)

    resolved_provider = provider or get_settings().recommendation_provider

    candidates = _load_eligible_candidates(db, seed=seed, viewer=viewer)

    if resolved_provider == "vector":
        scored = _score_with_vector(db, seed=seed, candidates=candidates)
        if scored:
            return _sort_and_trim(scored, limit=limit)
        # No vector matches — either the seed lacks an embedding
        # (lazy backfill failed) or every candidate is unembedded.
        # Fall through to the tag scorer so the UI still gets results.

    scored = _score_with_tags(seed=seed, candidates=candidates)
    return _sort_and_trim(scored, limit=limit)


def _load_eligible_candidates(
    db: Session,
    *,
    seed: Recipe,
    viewer: User,
) -> list[Recipe]:
    """All recipes the viewer is allowed to see, minus the seed.

    Shared by both scoring paths so the visibility rules live in a
    single place. ``joinedload`` keeps the per-candidate ingredient
    fetch from going N+1 in the tag scorer.
    """
    return (
        db.query(Recipe)
        .options(joinedload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient))
        .filter(Recipe.id != seed.id)
        .filter(
            or_(
                Recipe.user_id == viewer.id,
                Recipe.status == RecipeStatus.APPROVED,
            )
        )
        .all()
    )


def _score_with_tags(
    *,
    seed: Recipe,
    candidates: list[Recipe],
) -> list[RecipeRecommendation]:
    """Score every candidate with :func:`compute_similarity`.

    Drops 0.0 scores so the UI never receives no-overlap noise.
    """
    scored: list[RecipeRecommendation] = []
    for candidate in candidates:
        score = compute_similarity(seed, candidate)
        if score <= 0.0:
            continue
        scored.append(RecipeRecommendation(recipe=candidate, match_score=score))
    return scored


def _score_with_vector(
    db: Session,
    *,
    seed: Recipe,
    candidates: list[Recipe],
) -> list[RecipeRecommendation]:
    """Score every candidate via cosine similarity over stored embeddings.

    The seed's embedding is lazily backfilled on first use so this
    path stays usable for legacy rows that pre-date the feature. A
    candidate without ``embedding_values`` is silently skipped — the
    caller (``find_related_recipes``) detects the empty result and
    falls through to the tag scorer.
    """
    seed_vector = ensure_recipe_embedding(db, seed)
    if not seed_vector:
        return []

    scored: list[RecipeRecommendation] = []
    for candidate in candidates:
        candidate_vector = candidate.embedding_values
        if not candidate_vector:
            continue
        score = cosine_similarity(seed_vector, candidate_vector)
        if score <= 0.0:
            continue
        scored.append(RecipeRecommendation(recipe=candidate, match_score=score))
    return scored


def _sort_and_trim(
    scored: list[RecipeRecommendation],
    *,
    limit: int,
) -> list[RecipeRecommendation]:
    """Stable ranking: score DESC, then ``created_at`` DESC, then id.

    The id fallback keeps ordering deterministic when two recipes
    were created in the same second — important for tests that batch-
    create recipes via the seeded factory.
    """
    scored.sort(
        key=lambda rec: (
            -rec.match_score,
            -(rec.recipe.created_at.timestamp() if rec.recipe.created_at else 0.0),
            rec.recipe.id,
        )
    )
    return scored[:limit]
