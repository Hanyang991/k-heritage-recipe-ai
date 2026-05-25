"""Heritage → vector index orchestration.

``HeritageIndexer`` ties the embedding adapter, the vector-search
adapter, and the heritage-source list together:

* :meth:`index_documents` — embed a batch of :class:`HeritageDoc` and
  upsert them into the source-specific namespace. Source isolation is
  preserved: each doc's ``institution`` field routes the upsert (so a
  mixed batch from ``MultiSourceHeritageAdapter`` fans out to the
  correct namespaces automatically).
* :meth:`query` — embed a free-text query and run a nearest-neighbour
  search against one specific namespace.
* :meth:`query_all_sources` — fan out the same query vector across
  every known namespace and merge the results, mirroring the
  ``MultiSourceHeritageAdapter`` fan-in pattern. Used by the
  recipe-generate flow when the caller wants semantic results from
  every source at once.

Resilience contract (matches ``MultiSourceHeritageAdapter``):

* Per-namespace upsert/query failures are caught + logged; the run
  proceeds. The indexer tracks per-namespace error counts so callers
  can decide whether to retry the whole sync or accept partial
  progress.
* Unknown namespaces raise :class:`VectorIndexNotConfiguredError`
  loudly — that's a config bug, not a transient failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.services.embeddings.base import EmbeddingAdapter
from app.services.heritage.base import HeritageDoc
from app.services.vector_search.base import (
    VectorDatapoint,
    VectorIndexNotConfiguredError,
    VectorMatch,
    VectorSearchAdapter,
)

logger = logging.getLogger(__name__)


@dataclass
class IndexResult:
    """Result summary for a single :meth:`index_documents` call.

    Tracked per-namespace so operators can tell which source's upsert
    succeeded / failed in a mixed batch.
    """

    upserted: dict[str, int] = field(default_factory=dict)
    skipped_unknown_namespace: dict[str, int] = field(default_factory=dict)
    errored: dict[str, int] = field(default_factory=dict)

    @property
    def total_upserted(self) -> int:
        return sum(self.upserted.values())


@dataclass(frozen=True)
class CrossSourceMatch:
    """One :class:`VectorMatch` annotated with its source namespace."""

    namespace: str
    match: VectorMatch


def heritage_doc_id(doc: HeritageDoc) -> str:
    """Canonical ``datapoint_id`` for a :class:`HeritageDoc`.

    ``"{institution}:{external_id}"`` keeps the id stable across
    re-indexing runs and lines up with the ``(institution, external_id)``
    dedupe key already used by :class:`MultiSourceHeritageAdapter`. Both
    sides agree on identity so cross-references work without a side
    table.
    """
    return f"{doc.institution}:{doc.external_id}"


def heritage_doc_text(doc: HeritageDoc) -> str:
    """Concatenate the most informative HeritageDoc fields for embedding.

    We deliberately include the title TWICE (once verbatim, once in the
    summary block) because titles carry the heaviest semantic signal for
    short-query retrieval and Vertex AI's text-embedding-005 weights
    early tokens slightly more than late ones.
    """
    parts: list[str] = [doc.title]
    if doc.summary:
        parts.append(doc.summary)
    if doc.original_text:
        # Truncate raw original_text to keep embed cost predictable.
        parts.append(doc.original_text[:2000])
    if doc.period:
        parts.append(f"시대: {doc.period}")
    if doc.region:
        parts.append(f"지역: {doc.region}")
    if doc.category:
        parts.append(f"분류: {doc.category}")
    return "\n".join(p for p in parts if p)


def heritage_doc_restricts(doc: HeritageDoc) -> dict[str, list[str]]:
    """Build Vertex-AI ``restricts`` for filterable axes.

    Source is already the namespace, so it's intentionally NOT
    duplicated here. We expose ``period`` / ``region`` / ``category``
    for downstream filtering (e.g. recipe-generate restricting matches
    to a target era).
    """
    restricts: dict[str, list[str]] = {}
    if doc.period:
        restricts["period"] = [doc.period]
    if doc.region:
        restricts["region"] = [doc.region]
    if doc.category:
        restricts["category"] = [doc.category]
    return restricts


def heritage_doc_metadata(doc: HeritageDoc) -> dict[str, str]:
    """Plain JSON metadata echoed back at query time.

    Vertex AI Vector Search doesn't persist arbitrary metadata on the
    server side — production would store this in a side-table keyed by
    ``datapoint_id`` (out of scope for this PR; see todo.md §1.3.1).
    The mock provider keeps it in memory so tests can assert on it.
    """
    md: dict[str, str] = {
        "title": doc.title,
        "institution": doc.institution,
        "license": doc.license,
    }
    if doc.year is not None:
        md["year"] = str(doc.year)
    if doc.period:
        md["period"] = doc.period
    if doc.region:
        md["region"] = doc.region
    return md


class HeritageIndexer:
    """Embed + upsert + query heritage documents across per-source namespaces.

    Two upstream services are injected so the indexer is fully testable
    with mocks: an :class:`EmbeddingAdapter` for text → vector and a
    :class:`VectorSearchAdapter` for namespaced storage.

    ``allowed_namespaces`` defaults to the vector adapter's
    ``known_namespaces()`` — this keeps the indexer in sync with the
    configured Vertex AI indices without duplicating the list at the
    call site.
    """

    def __init__(
        self,
        *,
        embedder: EmbeddingAdapter,
        vector_store: VectorSearchAdapter,
        allowed_namespaces: list[str] | None = None,
    ) -> None:
        self._embedder = embedder
        self._vector_store = vector_store
        if allowed_namespaces is None:
            allowed_namespaces = vector_store.known_namespaces()
        if not allowed_namespaces:
            raise ValueError("HeritageIndexer requires at least one allowed namespace")
        self._allowed = set(allowed_namespaces)

    @property
    def allowed_namespaces(self) -> list[str]:
        # Stable-sorted for deterministic admin / log output.
        return sorted(self._allowed)

    def index_documents(self, docs: list[HeritageDoc]) -> IndexResult:
        """Embed and upsert ``docs``, routing each doc to its source's namespace.

        Docs are grouped by ``institution`` so each source only takes a
        single ``upsertDatapoints`` round-trip per batch. Docs from
        unknown institutions are skipped (counted in
        ``skipped_unknown_namespace``) rather than dropped silently —
        operators can audit the count post-run.
        """
        result = IndexResult()
        if not docs:
            return result

        # Bucket docs by source namespace, dropping unknown sources.
        by_namespace: dict[str, list[HeritageDoc]] = {}
        for doc in docs:
            namespace = doc.institution
            if namespace not in self._allowed:
                result.skipped_unknown_namespace[namespace] = (
                    result.skipped_unknown_namespace.get(namespace, 0) + 1
                )
                logger.warning(
                    "heritage indexer: skipping doc %s — namespace %r not in allowed list %r",
                    doc.external_id,
                    namespace,
                    sorted(self._allowed),
                )
                continue
            by_namespace.setdefault(namespace, []).append(doc)

        for namespace, ns_docs in by_namespace.items():
            try:
                texts = [heritage_doc_text(d) for d in ns_docs]
                embeddings = self._embedder.embed(texts)
                datapoints = [
                    VectorDatapoint(
                        datapoint_id=heritage_doc_id(d),
                        values=emb.values,
                        restricts=heritage_doc_restricts(d),
                        metadata=heritage_doc_metadata(d),
                    )
                    for d, emb in zip(ns_docs, embeddings, strict=True)
                ]
                self._vector_store.upsert(namespace, datapoints)
            except Exception as exc:  # noqa: BLE001 - resilience boundary
                logger.exception(
                    "heritage indexer: upsert failed for namespace %r: %s",
                    namespace,
                    exc,
                )
                result.errored[namespace] = result.errored.get(namespace, 0) + len(ns_docs)
                continue
            result.upserted[namespace] = result.upserted.get(namespace, 0) + len(ns_docs)
        return result

    def query(
        self,
        namespace: str,
        text: str,
        *,
        top_k: int = 10,
        restricts: dict[str, list[str]] | None = None,
    ) -> list[VectorMatch]:
        """Embed ``text`` and search ``namespace`` for nearest neighbours.

        Raises:
            VectorIndexNotConfiguredError: ``namespace`` is not in the
                indexer's allowed list. The vector store may raise the
                same error if ``namespace`` is unknown to it; both are
                surfaced unchanged for callers to distinguish "wrong
                source" from genuine "no matches".
        """
        if namespace not in self._allowed:
            raise VectorIndexNotConfiguredError(
                f"unknown namespace {namespace!r}; allowed: {sorted(self._allowed)!r}"
            )
        embeddings = self._embedder.embed([text])
        if not embeddings:
            return []
        return self._vector_store.query(
            namespace,
            embeddings[0].values,
            top_k=top_k,
            restricts=restricts,
        )

    def query_all_sources(
        self,
        text: str,
        *,
        top_k: int = 10,
        restricts: dict[str, list[str]] | None = None,
    ) -> list[CrossSourceMatch]:
        """Fan out a query across every allowed namespace and merge.

        Per-namespace failures are isolated (logged, that namespace's
        contribution drops to 0) so a single broken source can't take
        down the whole semantic-search flow. The merged result is
        re-sorted by score descending and trimmed to ``top_k`` total —
        consistent with :class:`MultiSourceHeritageAdapter`'s fan-in
        behaviour.
        """
        embeddings = self._embedder.embed([text])
        if not embeddings:
            return []
        query_vector = embeddings[0].values
        merged: list[CrossSourceMatch] = []
        for namespace in self.allowed_namespaces:
            try:
                matches = self._vector_store.query(
                    namespace,
                    query_vector,
                    top_k=top_k,
                    restricts=restricts,
                )
            except VectorIndexNotConfiguredError:
                # Indexer ↔ vector-store namespace mismatch is a config
                # bug — re-raise loudly so the operator notices.
                raise
            except Exception as exc:  # noqa: BLE001 - resilience boundary
                logger.exception(
                    "heritage indexer: cross-source query failed for namespace %r: %s",
                    namespace,
                    exc,
                )
                continue
            merged.extend(CrossSourceMatch(namespace=namespace, match=m) for m in matches)
        merged.sort(
            key=lambda c: (-c.match.score, c.namespace, c.match.datapoint_id),
        )
        return merged[:top_k]
