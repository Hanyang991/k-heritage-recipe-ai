"""Backfill recipe embeddings for rows that pre-date the vector variant.

Walks the ``recipes`` table in batches, computes the canonical embedding
text (see :func:`app.services.recipe_embeddings.compute_recipe_embedding_text`),
embeds it through the configured ``EMBEDDING_PROVIDER``, and stores the
vector on ``recipes.embedding_values``. Idempotent — a second run with
``force=False`` (default) is a no-op because every row already has an
embedding; pass ``force=True`` after changing the embedding text format
or swapping the provider.

Usage
-----

::

    # ad-hoc run against whatever EMBEDDING_PROVIDER is configured
    python -m app.jobs.backfill_recipe_embeddings

    # admin-triggered (see POST /v1/admin/recipes/embeddings/backfill)

Returns a structured :class:`RecipeEmbeddingBackfillReport` so the admin
endpoint can echo per-batch counts back to operators without parsing
log lines.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session, joinedload

from app.db.session import SessionLocal
from app.models.ingredient import RecipeIngredient
from app.models.recipe import Recipe
from app.services.recipe_embeddings import store_recipe_embedding

logger = logging.getLogger(__name__)


DEFAULT_BATCH_SIZE = 64


@dataclass(slots=True)
class RecipeEmbeddingBackfillReport:
    """Per-run counts surfaced by :func:`run_recipe_embedding_backfill`.

    ``scanned`` is every recipe the walker touched (regardless of
    success). ``embedded`` is the subset that received a non-empty
    vector in this run. ``skipped_already_embedded`` is non-zero when
    ``force=False`` and pre-embedded rows were encountered (the
    default path on a re-run after a partial failure).
    """

    scanned: int = 0
    embedded: int = 0
    skipped_already_embedded: int = 0
    failures: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def run_recipe_embedding_backfill(
    *,
    session: Session | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    force: bool = False,
) -> RecipeEmbeddingBackfillReport:
    """Embed every recipe missing ``embedding_values`` (or every recipe
    when ``force=True``).

    ``session`` defaults to a freshly opened ``SessionLocal`` so the
    job can run from a cron worker without taking a FastAPI request
    scope. The admin endpoint passes its own request-scoped session.

    The walk processes recipes in primary-key chunks rather than a
    single ``ORDER BY id`` to keep memory flat on the multi-thousand-
    recipe table the project will reach by the end of beta.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    owns_session = session is None
    session = session or SessionLocal()
    report = RecipeEmbeddingBackfillReport()
    try:
        last_id: str | None = None
        while True:
            query = session.query(Recipe).options(
                joinedload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient)
            )
            if last_id is not None:
                query = query.filter(Recipe.id > last_id)
            batch = query.order_by(Recipe.id).limit(batch_size).all()
            if not batch:
                break

            for recipe in batch:
                report.scanned += 1
                if recipe.embedding_values and not force:
                    report.skipped_already_embedded += 1
                    continue
                vector = store_recipe_embedding(session, recipe)
                if vector:
                    report.embedded += 1
                else:
                    report.failures += 1
            session.commit()
            last_id = batch[-1].id
    finally:
        if owns_session:
            session.close()
    return report


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    force = "--force" in sys.argv
    report = run_recipe_embedding_backfill(force=force)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entry
    raise SystemExit(main())
