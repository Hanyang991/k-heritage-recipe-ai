"""Postgres-backed vector-search storage row.

One row per ``(namespace, datapoint_id)`` pair. ``namespace`` is the
source key (``jangseogak`` / ``koreanstudies`` / ``nlk`` / ``gihohak``
/ ``nihc``) so per-source isolation matches the Vertex AI Vector
Search topology used by :class:`VertexAIVectorSearchAdapter`.

The actual embedding vector is stored as JSON (a plain ``list[float]``)
rather than via the ``pgvector`` extension's native ``vector(N)``
column type. This keeps the table portable across Postgres + SQLite
(tests run against SQLite, prod runs against Postgres) and lets
:class:`PgVectorSearchAdapter` rank candidates with a Python cosine
loop. The native pgvector / ``ORDER BY embedding <=> :v`` acceleration
is intentionally deferred — at the project's current scale (<1M
vectors across all heritage sources combined) Python brute-force
keeps query latency under 50ms with no extra dependencies. Once the
corpus grows past that, a follow-up migration can add the ``vector(N)``
column + IVFFlat index without changing the adapter's public surface.

``restricts`` mirrors Vertex AI's ``restricts`` query semantics —
``{key: [allowed_value, ...]}``. Used downstream for axis filters
such as ``period=조선전기`` or ``region=충청``. ``metadata`` carries
the side-table fields needed to reconstruct a :class:`HeritageDoc`
from a semantic-only hit (title / institution / region / period /
license / summary / year).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class VectorSearchDatapoint(Base, TimestampMixin):
    """One indexed embedding row, namespaced by heritage source."""

    __tablename__ = "vector_search_datapoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    namespace: Mapped[str] = mapped_column(String(64), nullable=False)
    datapoint_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Vector values stored as JSON list[float] for portability.
    values: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    # Vertex-AI-style restrict tags: ``{key: [allowed_value, ...]}``.
    restricts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # Metadata blob echoed back at query time. Field name avoids the
    # SQLAlchemy-reserved ``metadata`` attribute by suffixing ``_json``.
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint("namespace", "datapoint_id", name="uq_vsd_namespace_datapoint"),
        Index("ix_vsd_namespace", "namespace"),
    )
