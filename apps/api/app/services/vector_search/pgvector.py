"""Postgres-backed :class:`VectorSearchAdapter` for ``VECTOR_SEARCH_PROVIDER=pgvector``.

This is the **free** counterpart to :class:`VertexAIVectorSearchAdapter`
(PR #40). It reuses the project's existing Postgres database — no new
infrastructure, no GCP credentials — so operators can roll out the
heritage hybrid-retrieval path (PR #41) without provisioning Vertex AI
Vector Search.

Storage: one row per ``(namespace, datapoint_id)`` in the
:class:`VectorSearchDatapoint` table, with the vector serialised as a
JSON ``list[float]``. Per-source namespace isolation matches the
Vertex adapter's per-index topology — a query against namespace ``X``
only sees rows tagged ``namespace=X``.

Query algorithm: load all rows for the namespace (subject to the
``restricts`` AND-of-ORs filter), compute cosine similarity in pure
Python, sort, return top-k. This brute-force approach is intentionally
simple — at the project's heritage-corpus scale (<1M total vectors)
ranking latency stays under ~50ms even on cold cache. When the corpus
crosses ~1M vectors, a follow-up migration can add the pgvector
extension's native ``vector(N)`` column + IVFFlat / HNSW index and a
``query`` fast-path that delegates ranking to Postgres via the
``<=>`` (cosine distance) operator — without changing this adapter's
public surface (callers still see :class:`VectorMatch` results).

Resilience contract (matches :class:`MockVectorSearchAdapter`):

* Unknown namespaces raise :class:`VectorIndexNotConfiguredError`
  loudly — that's a config bug, not a transient failure.
* Empty namespaces return ``[]`` (no error). This lets the indexer
  query before the first upsert without special-casing.
* Upserts are idempotent — re-inserting the same ``datapoint_id``
  replaces the existing row, matching Vertex AI's
  ``upsertDatapoints`` semantics.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Callable
from typing import cast

from sqlalchemy.orm import Session, sessionmaker

from app.models.vector_search_datapoint import VectorSearchDatapoint
from app.services.vector_search.base import (
    VectorDatapoint,
    VectorIndexNotConfiguredError,
    VectorMatch,
    VectorSearchAdapter,
)


class PgVectorSearchAdapter(VectorSearchAdapter):
    """Postgres-backed vector store with per-source namespace isolation.

    Constructed with:

    * a SQLAlchemy ``sessionmaker`` (or any zero-arg callable returning
      a ``Session``) so the adapter is decoupled from FastAPI's request
      scope — the indexer runs from background jobs and admin
      endpoints alike;
    * a list of declared namespaces. Operations against unknown
      namespaces raise :class:`VectorIndexNotConfiguredError`, matching
      the mock and Vertex adapters' contract.
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] | sessionmaker[Session],
        namespaces: list[str],
    ) -> None:
        if not namespaces:
            raise ValueError("PgVectorSearchAdapter requires at least one namespace")
        # Cast `sessionmaker` to the callable shape mypy expects.
        self._session_factory = cast(Callable[[], Session], session_factory)
        # OrderedDict preserves insertion order so ``known_namespaces``
        # gives deterministic output for admin / log purposes.
        self._namespaces: OrderedDict[str, None] = OrderedDict((ns, None) for ns in namespaces)

    def known_namespaces(self) -> list[str]:
        return list(self._namespaces.keys())

    def upsert(self, namespace: str, datapoints: list[VectorDatapoint]) -> None:
        self._require_namespace(namespace)
        if not datapoints:
            return
        session = self._session_factory()
        try:
            # Pull existing rows for the (namespace, datapoint_id) pairs in
            # one round-trip rather than N individual SELECTs. SQLAlchemy
            # turns this into ``WHERE namespace = ? AND datapoint_id IN (...)``.
            incoming_ids = [dp.datapoint_id for dp in datapoints]
            existing = {
                row.datapoint_id: row
                for row in session.query(VectorSearchDatapoint)
                .filter(
                    VectorSearchDatapoint.namespace == namespace,
                    VectorSearchDatapoint.datapoint_id.in_(incoming_ids),
                )
                .all()
            }
            for dp in datapoints:
                row = existing.get(dp.datapoint_id)
                if row is None:
                    session.add(
                        VectorSearchDatapoint(
                            namespace=namespace,
                            datapoint_id=dp.datapoint_id,
                            values=list(dp.values),
                            restricts={k: list(v) for k, v in dp.restricts.items()},
                            metadata_json=dict(dp.metadata),
                        )
                    )
                else:
                    row.values = list(dp.values)
                    row.restricts = {k: list(v) for k, v in dp.restricts.items()}
                    row.metadata_json = dict(dp.metadata)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def query(
        self,
        namespace: str,
        vector: list[float],
        *,
        top_k: int = 10,
        restricts: dict[str, list[str]] | None = None,
    ) -> list[VectorMatch]:
        self._require_namespace(namespace)
        if top_k <= 0:
            return []
        session = self._session_factory()
        try:
            rows = (
                session.query(VectorSearchDatapoint)
                .filter(VectorSearchDatapoint.namespace == namespace)
                .all()
            )
        finally:
            session.close()
        results: list[VectorMatch] = []
        for row in rows:
            if not _matches_restricts(row.restricts or {}, restricts):
                continue
            score = _cosine_similarity(vector, row.values or [])
            if score > 1.0:
                score = 1.0
            elif score < 0.0:
                score = 0.0
            results.append(
                VectorMatch(
                    datapoint_id=row.datapoint_id,
                    score=score,
                    metadata=dict(row.metadata_json or {}),
                )
            )
        # Stable sort: highest score first, ties broken by datapoint_id
        # for deterministic test / admin output.
        results.sort(key=lambda m: (-m.score, m.datapoint_id))
        return results[:top_k]

    def _require_namespace(self, namespace: str) -> None:
        if namespace not in self._namespaces:
            raise VectorIndexNotConfiguredError(
                f"unknown namespace {namespace!r}; known: {list(self._namespaces.keys())!r}"
            )


def _matches_restricts(
    row_restricts: dict[str, list[str]],
    query_restricts: dict[str, list[str]] | None,
) -> bool:
    """Vertex-AI-compatible AND-of-ORs restrict matching.

    Mirrors :func:`MockVectorSearchAdapter._matches_restricts` so both
    adapters return the same candidate set for the same inputs —
    important for the hybrid retrieval blend.
    """
    if not query_restricts:
        return True
    for key, allowed in query_restricts.items():
        row_values = row_restricts.get(key)
        if not row_values:
            return False
        if not set(row_values).intersection(allowed):
            return False
    return True


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"vector dimension mismatch: {len(a)} vs {len(b)}")
    if not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
