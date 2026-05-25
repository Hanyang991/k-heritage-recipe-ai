"""Related-recipe recommendation service (todo §1.4 "관련 레시피 추천").

Implements a **tag + ingredient overlap** scorer so the frontend can show
"이런 레시피는 어때요?" cards next to a seed recipe without any external
infrastructure dependency. The shape of the public function
(:func:`find_related_recipes`) is intentionally identical to what a future
vector-similarity implementation would expose — the router only knows about
``RecipeRecommendation`` records, so swapping the backend to embeddings
(via the existing ``app.services.embeddings`` + ``app.services.vector_search``
adapters) later is a single-file change.

Why tag-based first (not vector first):

* The user-recipe corpus is small (per-user O(N), platform-wide O(N×M)) so
  Jaccard / categorical overlap finishes in <50ms cold-cache on SQLite —
  vector indexing latency would dominate at this scale.
* The Recipe model already carries dense categorical signal (region / era /
  diet / menu_type / keyword + ingredient lines) that maps 1:1 to user
  intent. Embeddings would mostly re-derive the same signal from free text.
* Tag scoring is fully deterministic, so it plays nicely with the existing
  pytest fixtures (mock LLM / mock heritage) without requiring a vector
  index to be backfilled in test setup.

Scoring weights are exported as module constants so they're trivially
A/B-able from a future settings module without touching call sites.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models.ingredient import RecipeIngredient
from app.models.recipe import Recipe, RecipeStatus
from app.models.user import User

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

    Candidates with a final score of ``0.0`` are dropped — there is no
    point surfacing a "related" recipe that shares nothing with the
    seed. Ties are broken by ``created_at DESC`` so freshly-generated
    recipes float over older ones.
    """
    if limit <= 0:
        return []
    limit = min(limit, MAX_RELATED_LIMIT)

    query = (
        db.query(Recipe)
        .options(joinedload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient))
        .filter(Recipe.id != seed.id)
        .filter(
            or_(
                Recipe.user_id == viewer.id,
                Recipe.status == RecipeStatus.APPROVED,
            )
        )
    )

    # Materialise candidates once so we can score in pure Python — for
    # the per-user O(N) corpus we expect at MVP scale this is faster
    # than SQL-side weighted-sum SQL across portable backends (SQLite +
    # Postgres) and keeps the scoring formula readable.
    candidates = query.all()

    scored: list[RecipeRecommendation] = []
    for candidate in candidates:
        score = compute_similarity(seed, candidate)
        if score <= 0.0:
            continue
        scored.append(RecipeRecommendation(recipe=candidate, match_score=score))

    scored.sort(
        key=lambda rec: (
            -rec.match_score,
            -(rec.recipe.created_at.timestamp() if rec.recipe.created_at else 0.0),
        )
    )
    return scored[:limit]
