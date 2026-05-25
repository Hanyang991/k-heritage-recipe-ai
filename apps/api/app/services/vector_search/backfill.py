"""Heritage corpus → vector index backfill orchestration.

Drives the *first* indexing batch: walks a list of seed queries through
the configured keyword heritage adapter, deduplicates the collected
documents by ``(institution, external_id)``, and feeds the result to
:class:`HeritageIndexer` in chunks. Intended to be run once after the
deployment switches to ``HERITAGE_RETRIEVAL_MODE=hybrid`` +
``VECTOR_SEARCH_PROVIDER=pgvector`` so the semantic side of hybrid
retrieval has *anything* to return.

The runner uses the keyword adapter directly (via
:func:`app.services.heritage.get_keyword_heritage_adapter`) rather than
the hybrid wrapper — the semantic side has nothing useful to return on
an empty index and would just slow the seed walk down.

Most archival APIs require a search keyword (you can't list "all
documents"), so the runner is driven by a configurable list of seed
queries (:data:`DEFAULT_BACKFILL_QUERIES` by default, overridable via
``HERITAGE_BACKFILL_QUERIES``). Each query returns up to
``per_query_limit`` results from every source the keyword adapter fans
into. Results are deduplicated across queries so repeated overlaps
don't double-embed the same doc.

Resilience contract mirrors :class:`HeritageIndexer.index_documents`:
per-query search failures are logged + skipped (the surviving queries
still contribute), per-namespace upsert failures are surfaced in the
returned counts so operators can decide whether to retry a single
source or accept partial progress.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.services.heritage.base import HeritageAdapter, HeritageDoc
from app.services.vector_search.indexer import HeritageIndexer, IndexResult

logger = logging.getLogger(__name__)


# Curated default backfill query pool. Korean food, ritual, and
# everyday-life terms chosen to cross-cut all four open-API heritage
# sources without leaning too hard on any single one's vocabulary:
#
# * ``음식 / 의궤 / 농서 / 잔치 / 제사`` — domain anchors that surface
#   on every source, including the 의궤 / 농서 corpora that 장서각 +
#   NLK's KORCIS index disproportionately well.
# * ``떡 / 죽 / 국 / 면 / 밥 / 김치 / 장 / 술 / 차`` — concrete dishes
#   so the rank-decay shape inside each source's top-50 surfaces the
#   richest food-adjacent records, not just the most generic ones.
# * ``전 / 찜 / 탕 / 어 / 육 / 채 / 나물 / 약식 / 병과 / 정과`` —
#   secondary cuisine vocabulary that catches 의궤 menu rolls 장서각
#   and 한국학자료포털 host but that the broader anchors miss.
DEFAULT_BACKFILL_QUERIES: tuple[str, ...] = (
    "음식",
    "의궤",
    "농서",
    "잔치",
    "제사",
    "떡",
    "죽",
    "국",
    "면",
    "밥",
    "김치",
    "장",
    "술",
    "차",
    "전",
    "찜",
    "탕",
    "어",
    "육",
    "채",
    "나물",
    "약식",
    "병과",
    "정과",
)


@dataclass
class BackfillReport:
    """Per-run stats from :meth:`HeritageBackfillRunner.run`."""

    queries_attempted: int = 0
    queries_succeeded: int = 0
    # ``query → last error message`` for failed seed queries. Bounded
    # naturally by the seed-query pool size, so safe to inline.
    queries_failed: dict[str, str] = field(default_factory=dict)
    unique_docs_collected: int = 0
    # ``institution → count`` of unique docs collected before indexing.
    # Useful for operators to spot lopsided coverage (e.g. all hits
    # came from one source because the others were rate-limited).
    docs_per_source: dict[str, int] = field(default_factory=dict)
    index_result: IndexResult = field(default_factory=IndexResult)

    @property
    def total_upserted(self) -> int:
        return self.index_result.total_upserted

    def as_dict(self) -> dict[str, Any]:
        """JSON-friendly snapshot for admin / CLI surfaces."""
        return {
            "queries_attempted": self.queries_attempted,
            "queries_succeeded": self.queries_succeeded,
            "queries_failed": dict(self.queries_failed),
            "unique_docs_collected": self.unique_docs_collected,
            "docs_per_source": dict(self.docs_per_source),
            "upserted_per_namespace": dict(self.index_result.upserted),
            "errored_per_namespace": dict(self.index_result.errored),
            "skipped_unknown_namespace": dict(self.index_result.skipped_unknown_namespace),
            "total_upserted": self.total_upserted,
        }


class HeritageBackfillRunner:
    """Walks seed queries through a heritage adapter + indexer.

    The runner is deliberately stateless across calls — re-running with
    the same settings just re-issues the same query walk. The vector
    store's upsert is idempotent by ``(namespace, datapoint_id)``, so
    re-running is safe (it refreshes the embeddings to match the
    current ``EMBEDDING_PROVIDER`` setting).
    """

    def __init__(
        self,
        *,
        heritage_adapter: HeritageAdapter,
        indexer: HeritageIndexer,
        queries: Iterable[str] | None = None,
        per_query_limit: int = 50,
        batch_size: int = 50,
    ) -> None:
        if per_query_limit <= 0:
            raise ValueError("per_query_limit must be positive")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        cleaned = [q.strip() for q in (queries or DEFAULT_BACKFILL_QUERIES) if q and q.strip()]
        if not cleaned:
            raise ValueError("at least one non-empty query is required")
        self._heritage_adapter = heritage_adapter
        self._indexer = indexer
        self._queries = cleaned
        self._per_query_limit = per_query_limit
        self._batch_size = batch_size

    @property
    def queries(self) -> list[str]:
        return list(self._queries)

    def run(self) -> BackfillReport:
        """Execute the seed walk and return a per-source stats report.

        Two passes:

        1. **Collect**: call ``heritage_adapter.search`` for each seed
           query. Per-query exceptions are caught and recorded so a
           single transport blip doesn't abort the whole walk. Docs
           are deduplicated by ``(institution, external_id)`` so the
           same record showing up across multiple queries is only
           embedded once.
        2. **Index**: feed the deduplicated docs to
           :meth:`HeritageIndexer.index_documents` in chunks of
           ``batch_size``. The indexer handles per-namespace routing,
           embedding, and upsert; its per-namespace error counts are
           merged into the final report.
        """
        report = BackfillReport()
        seen: dict[tuple[str, str], HeritageDoc] = {}
        for query in self._queries:
            report.queries_attempted += 1
            try:
                matches = self._heritage_adapter.search(query, limit=self._per_query_limit)
            except Exception as exc:  # noqa: BLE001 - resilience boundary
                logger.warning("backfill: query %r failed: %s", query, exc)
                report.queries_failed[query] = str(exc)
                continue
            report.queries_succeeded += 1
            for match in matches:
                doc = match.document
                key = (doc.institution, doc.external_id)
                if key in seen:
                    continue
                seen[key] = doc

        for institution, _ in seen.keys():
            report.docs_per_source[institution] = (
                report.docs_per_source.get(institution, 0) + 1
            )
        report.unique_docs_collected = len(seen)

        docs = list(seen.values())
        aggregate = IndexResult()
        for start in range(0, len(docs), self._batch_size):
            chunk = docs[start : start + self._batch_size]
            _merge_index_result(aggregate, self._indexer.index_documents(chunk))
        report.index_result = aggregate

        logger.info(
            "heritage backfill complete: queries=%d/%d unique_docs=%d upserted=%d "
            "errored=%s skipped=%s",
            report.queries_succeeded,
            report.queries_attempted,
            report.unique_docs_collected,
            report.total_upserted,
            dict(report.index_result.errored),
            dict(report.index_result.skipped_unknown_namespace),
        )
        return report


def _merge_index_result(aggregate: IndexResult, other: IndexResult) -> None:
    """Fold ``other``'s per-namespace counters into ``aggregate``."""
    for namespace, count in other.upserted.items():
        aggregate.upserted[namespace] = aggregate.upserted.get(namespace, 0) + count
    for namespace, count in other.skipped_unknown_namespace.items():
        aggregate.skipped_unknown_namespace[namespace] = (
            aggregate.skipped_unknown_namespace.get(namespace, 0) + count
        )
    for namespace, count in other.errored.items():
        aggregate.errored[namespace] = aggregate.errored.get(namespace, 0) + count


def run_heritage_backfill(
    queries: Iterable[str] | None = None,
    *,
    per_query_limit: int | None = None,
    batch_size: int | None = None,
) -> BackfillReport:
    """High-level entry point that wires settings + factories together.

    Imports the heritage / embedding / vector-search factories lazily
    so a recipe-generate request path that never touches the backfill
    module isn't forced to instantiate any of them at import time.
    """
    from app.config import get_settings
    from app.services.embeddings import get_embedding_adapter
    from app.services.heritage import get_keyword_heritage_adapter
    from app.services.vector_search import get_vector_search_adapter

    settings = get_settings()
    runner = HeritageBackfillRunner(
        heritage_adapter=get_keyword_heritage_adapter(),
        indexer=HeritageIndexer(
            embedder=get_embedding_adapter(),
            vector_store=get_vector_search_adapter(),
        ),
        queries=list(queries) if queries is not None else (settings.heritage_backfill_queries_list or None),
        per_query_limit=per_query_limit
        if per_query_limit is not None
        else settings.heritage_backfill_per_query_limit,
        batch_size=batch_size
        if batch_size is not None
        else settings.heritage_backfill_batch_size,
    )
    return runner.run()


__all__ = [
    "DEFAULT_BACKFILL_QUERIES",
    "BackfillReport",
    "HeritageBackfillRunner",
    "run_heritage_backfill",
]
