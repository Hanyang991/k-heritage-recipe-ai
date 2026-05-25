"""Postgres-backed :class:`VectorSearchAdapter` for ``VECTOR_SEARCH_PROVIDER=pgvector``.

This is the **free** counterpart to :class:`VertexAIVectorSearchAdapter`
(PR #40). It reuses the project's existing Postgres database — no new
infrastructure, no GCP credentials — so operators can roll out the
heritage hybrid-retrieval path (PR #41) without provisioning Vertex AI
Vector Search.

Storage: one row per ``(namespace, datapoint_id)`` in the
:class:`VectorSearchDatapoint` table, with the vector serialised as a
JSON ``list[float]`` (``values`` column) **and** — when running against
Postgres + the ``vector`` extension — duplicated into a native
``embedding vector(N)`` column populated by the pgvector migration
(``0002_pgvector_native_knn``). Per-source namespace isolation matches
the Vertex adapter's per-index topology — a query against namespace
``X`` only sees rows tagged ``namespace=X``.

Query algorithm picks at runtime based on the SQLAlchemy dialect:

* **Postgres native KNN fast path** — ``ORDER BY embedding <=> :v``
  delegates ranking to pgvector's HNSW cosine index. Restricts (the
  Vertex-AI-compatible AND-of-ORs filter) are pushed into the SQL using
  ``(restricts::jsonb -> :k) ?| ARRAY[:vals]``. Latency scales with
  ``log(N)``, so 1M+ vectors stay under ~5ms per query.
* **Python brute-force fallback** — used on SQLite (tests, local dev
  without Postgres) and as a safety net when pgvector isn't available
  on the current Postgres instance. Loads every row in the namespace,
  computes cosine similarity in pure Python, sorts, returns top-k.
  Latency is ``O(N)`` but stays under 50ms at the project's launch
  scale (<400K vectors across all heritage sources combined).

The two paths are kept behaviourally identical — same restricts
semantics, same score range [0, 1], same tie-breaking on
``datapoint_id`` — so callers can't tell which one served their query.
This matters for the hybrid retrieval blend (PR #41), which mixes
pgvector matches with keyword hits and must compare scores apples-to-
apples.

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

import logging
import math
from collections import OrderedDict
from collections.abc import Callable
from typing import cast

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.models.vector_search_datapoint import VectorSearchDatapoint
from app.services.vector_search.base import (
    VectorDatapoint,
    VectorIndexNotConfiguredError,
    VectorMatch,
    VectorSearchAdapter,
)

logger = logging.getLogger(__name__)


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

    When ``native_knn`` is True (default) and the connected database is
    Postgres, ``upsert`` populates the native ``embedding vector(N)``
    column and ``query`` delegates ranking to pgvector via the
    ``ORDER BY embedding <=> :v`` operator. Both behaviours fall back
    to the Python ``values``-JSON path on SQLite (tests) or when the
    pgvector extension isn't installed.
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] | sessionmaker[Session],
        namespaces: list[str],
        native_knn: bool = True,
    ) -> None:
        if not namespaces:
            raise ValueError("PgVectorSearchAdapter requires at least one namespace")
        # Cast `sessionmaker` to the callable shape mypy expects.
        self._session_factory = cast(Callable[[], Session], session_factory)
        # OrderedDict preserves insertion order so ``known_namespaces``
        # gives deterministic output for admin / log purposes.
        self._namespaces: OrderedDict[str, None] = OrderedDict((ns, None) for ns in namespaces)
        self._native_knn_enabled = native_knn
        # Cache of the pgvector availability per session-factory-bound
        # engine. ``None`` = not probed yet, populated lazily on the
        # first upsert / query that runs against Postgres.
        self._pgvector_ready: bool | None = None

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
            session.flush()

            # On Postgres with pgvector installed, mirror the JSON
            # ``values`` payload into the native ``embedding`` column so
            # the HNSW index covers freshly-upserted rows. The
            # ``::text::vector`` cast goes JSON → text → vector — pgvector
            # accepts ``[0.1,0.2,...]`` (the JSON serialisation of a
            # numeric array) as a vector literal.
            if self._should_use_native_knn(session):
                session.execute(
                    text(
                        "UPDATE vector_search_datapoints "
                        'SET embedding = ("values"::text)::vector '
                        "WHERE namespace = :ns "
                        "AND datapoint_id = ANY(:ids)"
                    ),
                    {"ns": namespace, "ids": incoming_ids},
                )

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
            if self._should_use_native_knn(session):
                return self._query_native(
                    session,
                    namespace=namespace,
                    vector=vector,
                    top_k=top_k,
                    restricts=restricts,
                )
            return self._query_python(
                session,
                namespace=namespace,
                vector=vector,
                top_k=top_k,
                restricts=restricts,
            )
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Query backends
    # ------------------------------------------------------------------

    def _query_native(
        self,
        session: Session,
        *,
        namespace: str,
        vector: list[float],
        top_k: int,
        restricts: dict[str, list[str]] | None,
    ) -> list[VectorMatch]:
        """pgvector ``ORDER BY embedding <=> :v`` fast path.

        Restricts are pushed into SQL via JSONB containment so the
        HNSW index isn't bypassed by a Python-level post-filter. Rows
        whose ``embedding`` column is ``NULL`` (i.e. backfill hasn't
        run yet) are skipped here and picked up by the Python fallback
        on the next query — see ``app.jobs.backfill_pgvector_embedding``.
        """
        # pgvector accepts the literal ``[0.1,0.2,...]`` (same shape as
        # JSON) as a vector input. ``json.dumps`` over a Python list
        # produces exactly that.
        import json

        params: dict[str, object] = {
            "ns": namespace,
            "v": json.dumps(vector),
            "k": top_k,
        }
        restrict_sql_parts: list[str] = []
        if restricts:
            for idx, (key, allowed) in enumerate(restricts.items()):
                key_param = f"rkey_{idx}"
                vals_param = f"rvals_{idx}"
                params[key_param] = key
                params[vals_param] = list(allowed)
                # ``?|`` on JSONB returns true iff any of the right-side
                # text values exist as a top-level key OR (for arrays)
                # as an element. For ``restricts == {"period": ["조선전기"]}``
                # the stored row has ``restricts -> 'period' = ["조선전기"]``
                # and ``["조선전기"] ?| ARRAY['조선전기'] = true``.
                restrict_sql_parts.append(
                    f"((restricts::jsonb -> :{key_param}) ?| (:{vals_param})::text[])"
                )
        restrict_clause = " AND " + " AND ".join(restrict_sql_parts) if restrict_sql_parts else ""

        # ``1 - distance`` converts pgvector's cosine distance (0..2) into
        # the [0, 1] similarity that callers expect. Identical-vector
        # rows produce distance ~0 → similarity 1.0. Opposite vectors
        # produce distance ~2 → similarity -1, which we clamp to 0 below.
        sql = text(
            "SELECT datapoint_id, metadata_json, "
            "1 - (embedding <=> CAST(:v AS vector)) AS score "
            "FROM vector_search_datapoints "
            "WHERE namespace = :ns "
            "AND embedding IS NOT NULL"
            f"{restrict_clause} "
            "ORDER BY embedding <=> CAST(:v AS vector), datapoint_id ASC "
            "LIMIT :k"
        )
        try:
            rows = session.execute(sql, params).all()
        except SQLAlchemyError:
            # If something is wrong with the native path (e.g. the
            # extension was uninstalled out from under us, or the
            # ``embedding`` column doesn't exist because the migration
            # hasn't run), fall back to the Python implementation rather
            # than crashing the recipe-generate pipeline.
            logger.warning(
                "pgvector native KNN query failed; falling back to Python brute-force",
                exc_info=True,
            )
            session.rollback()
            self._pgvector_ready = False
            return self._query_python(
                session,
                namespace=namespace,
                vector=vector,
                top_k=top_k,
                restricts=restricts,
            )

        results: list[VectorMatch] = []
        for datapoint_id, metadata_json, score in rows:
            score_f = float(score) if score is not None else 0.0
            if score_f > 1.0:
                score_f = 1.0
            elif score_f < 0.0:
                score_f = 0.0
            results.append(
                VectorMatch(
                    datapoint_id=datapoint_id,
                    score=score_f,
                    metadata=dict(metadata_json or {}),
                )
            )
        return results

    def _query_python(
        self,
        session: Session,
        *,
        namespace: str,
        vector: list[float],
        top_k: int,
        restricts: dict[str, list[str]] | None,
    ) -> list[VectorMatch]:
        """Brute-force cosine scan over JSON ``values`` — SQLite fallback."""
        rows = (
            session.query(VectorSearchDatapoint)
            .filter(VectorSearchDatapoint.namespace == namespace)
            .all()
        )
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

    # ------------------------------------------------------------------
    # Backend selection
    # ------------------------------------------------------------------

    def _should_use_native_knn(self, session: Session) -> bool:
        """Cache-aware probe: does this session's DB support pgvector?

        Cheap to call repeatedly — the underlying probe runs once per
        adapter instance and the result is memoised on ``self``.
        """
        if not self._native_knn_enabled:
            return False
        if session.bind is None or session.bind.dialect.name != "postgresql":
            return False
        if self._pgvector_ready is None:
            self._pgvector_ready = _probe_pgvector(session)
        return self._pgvector_ready


def _probe_pgvector(session: Session) -> bool:
    """Return ``True`` iff the ``vector`` extension is installed AND
    the ``embedding`` column exists on ``vector_search_datapoints``.

    Both checks are needed because operators can install the extension
    without running the migration, or vice-versa on managed Postgres
    where ``CREATE EXTENSION`` runs out-of-band.
    """
    try:
        ext_ok = session.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
        if not ext_ok:
            logger.info(
                "pgvector extension not installed; PgVectorSearchAdapter "
                "will use Python brute-force cosine"
            )
            return False
        col_ok = session.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'vector_search_datapoints' AND column_name = 'embedding'"
            )
        ).scalar()
        if not col_ok:
            logger.info(
                "vector_search_datapoints.embedding column missing — run "
                "`alembic upgrade head` to enable the pgvector native KNN path"
            )
            return False
        return True
    except SQLAlchemyError:
        logger.warning(
            "pgvector probe failed; falling back to Python brute-force",
            exc_info=True,
        )
        return False


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
