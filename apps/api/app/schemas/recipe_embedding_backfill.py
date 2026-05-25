"""Schemas for the recipe embedding backfill endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RecipeEmbeddingBackfillRequest(BaseModel):
    """Optional overrides for ``POST /v1/admin/recipes/embeddings/backfill``.

    Empty body is idiomatic — the default walks every recipe that
    still has ``embedding_values=NULL``. ``force=true`` re-embeds even
    rows that already have a stored vector (use after changing the
    embedding text format or swapping ``EMBEDDING_PROVIDER``).
    """

    batch_size: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Per-batch recipe count handed to the walker. Defaults to "
            "64. Tune down for memory-constrained workers or up for "
            "throughput on a large back catalogue."
        ),
    )
    force: bool = Field(
        default=False,
        description=(
            "Re-embed every recipe even if it already has a stored "
            "embedding. Required after a change to the canonical "
            "embedding-text format or the embedding provider."
        ),
    )


class RecipeEmbeddingBackfillResponse(BaseModel):
    """Per-run stats — mirrors :class:`RecipeEmbeddingBackfillReport`."""

    scanned: int
    embedded: int
    skipped_already_embedded: int
    failures: int
