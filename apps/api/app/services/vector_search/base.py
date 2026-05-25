"""Vector-search adapter contract — namespaced by heritage source.

The semantic-search side of the heritage pipeline is namespaced **by
source** (장서각 / 한국학자료포털 / 국립중앙도서관 / 기호유학 / 국사편찬위)
so that each archive's documents are indexed and queried independently:

* Each source maps to its own Vertex AI Vector Search index. This
  preserves source provenance for KOGL attribution (spec §13) and lets
  operators retire / re-build one source without touching the others.
* A query against a single namespace returns matches from that source
  only; a cross-source query fans out the same vector across every
  namespace and merges the results (delegated to ``HeritageIndexer``
  / ``MultiSourceHeritageAdapter``).

Two providers exist behind this protocol (selected by
:attr:`Settings.vector_search_provider`):

* ``mock`` — :class:`MockVectorSearchAdapter` stores datapoints in an
  in-process dict-of-lists, supports cosine-similarity ``query`` via
  brute-force scan. No network I/O. Used for tests, local dev, and as
  the graceful-degrade target when ``live`` is requested but Vertex
  AI Vector Search resources aren't provisioned.
* ``live`` — :class:`VertexAIVectorSearchAdapter` uses Vertex AI Vector
  Search ``upsertDatapoints`` (index endpoint) and ``findNeighbors``
  (deployed index endpoint).

Namespace resolution is data-driven (``VectorIndexConfig`` mapping per
source) so adding a new source is a config change rather than a code
change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class VectorDatapoint:
    """One indexed item: vector + provenance metadata.

    ``datapoint_id`` MUST be unique within a namespace; for heritage
    docs the canonical id is ``"{institution}:{external_id}"`` so
    re-indexing the same source naturally upserts.

    ``restricts`` are Vertex AI's filter tags (``namespace`` + allowed
    values). We use them for secondary axes such as
    ``period=조선전기`` / ``region=충청`` so a single index supports
    cross-axis filtering in addition to the per-source namespace.

    ``metadata`` is plain JSON that callers can echo back at query time
    (title, year, institution). Vertex AI Vector Search itself doesn't
    persist arbitrary metadata — the mock provider keeps it for tests
    and the live provider relies on a side-table keyed by
    ``datapoint_id`` for the same purpose (out of scope for this PR;
    see ``todo.md`` §1.3.1).
    """

    datapoint_id: str
    values: list[float]
    restricts: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorMatch:
    """One search result paired with its similarity score.

    ``score`` is similarity in ``[0, 1]`` (higher is better) — adapters
    are responsible for normalising distance metrics into this range so
    downstream code can compare scores across mock + live without
    knowing which provider produced them.
    """

    datapoint_id: str
    score: float
    metadata: dict[str, str] = field(default_factory=dict)


class VectorSearchAdapter(Protocol):
    """Per-namespace vector index protocol."""

    def upsert(self, namespace: str, datapoints: list[VectorDatapoint]) -> None:
        """Insert / replace ``datapoints`` in ``namespace``.

        Vertex AI's ``upsertDatapoints`` is idempotent: identical
        ``datapoint_id`` replaces the existing vector. The mock
        implementation mirrors this so tests can re-run seed scripts
        without manual cleanup.

        Raises:
            VectorIndexNotConfiguredError: ``namespace`` is not in the
                adapter's known-namespace map.
        """

    def query(
        self,
        namespace: str,
        vector: list[float],
        *,
        top_k: int = 10,
        restricts: dict[str, list[str]] | None = None,
    ) -> list[VectorMatch]:
        """Top-``top_k`` nearest neighbours of ``vector`` in ``namespace``.

        ``restricts`` filters the candidate pool to datapoints whose
        ``restricts[namespace]`` overlaps the requested values — same
        contract as Vertex AI Vector Search's ``restricts`` query
        parameter. Pass ``None`` (default) to search the entire
        namespace.

        Raises:
            VectorIndexNotConfiguredError: ``namespace`` is unknown.
        """

    def known_namespaces(self) -> list[str]:
        """Stable-sorted list of namespaces this adapter recognises.

        Used by the indexer / admin endpoints to enumerate destinations
        without hard-coding the source list. Order MUST be stable for
        deterministic test output.
        """


class VectorIndexNotConfiguredError(KeyError):
    """Raised when an operation targets an unknown namespace.

    Different from "no datapoints in this namespace" — the namespace
    itself isn't registered in the adapter's config map, so the caller
    is mis-using the API rather than querying an empty index.
    """
