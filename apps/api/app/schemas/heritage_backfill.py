"""Schemas for the heritage corpus → vector index backfill endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HeritageBackfillRequest(BaseModel):
    """Optional overrides for ``POST /v1/admin/heritage/index/backfill``.

    Empty body is intentional and idiomatic: the job is driven by
    settings + the curated default seed pool. The fields below let
    operators scope a one-off run (e.g. re-index after extending the
    seed pool) without redeploying.
    """

    queries: list[str] | None = Field(
        default=None,
        description=(
            "Override seed queries. Empty list / None → use "
            "``HERITAGE_BACKFILL_QUERIES`` (falling back to the curated "
            "``DEFAULT_BACKFILL_QUERIES`` pool when that is unset)."
        ),
    )
    per_query_limit: int | None = Field(
        default=None,
        gt=0,
        description="Override ``HERITAGE_BACKFILL_PER_QUERY_LIMIT`` for this run.",
    )
    batch_size: int | None = Field(
        default=None,
        gt=0,
        description="Override ``HERITAGE_BACKFILL_BATCH_SIZE`` for this run.",
    )


class HeritageBackfillResponse(BaseModel):
    """Per-run stats, mirroring :class:`BackfillReport.as_dict`."""

    queries_attempted: int
    queries_succeeded: int
    queries_failed: dict[str, str]
    unique_docs_collected: int
    docs_per_source: dict[str, int]
    upserted_per_namespace: dict[str, int]
    errored_per_namespace: dict[str, int]
    skipped_unknown_namespace: dict[str, int]
    total_upserted: int
