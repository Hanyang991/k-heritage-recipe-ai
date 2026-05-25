"""pgvector native KNN — add ``vector(768)`` column + HNSW cosine index.

This migration prepares the project for the ``~1M`` heritage-vector
scale that the current Python brute-force cosine path (PR #44) was only
designed to cover up to. The migration:

1. Installs the ``vector`` extension (``CREATE EXTENSION IF NOT EXISTS
   vector;``). The pgvector extension ships in the
   ``pgvector/pgvector:pg16`` Docker image used by ``docker-compose.yml``
   and is one ``CREATE EXTENSION`` away on the major managed services
   (AWS RDS / Aurora ≥ 15.2, GCP Cloud SQL ≥ 0.5.0, Supabase, Neon,
   Render). If the extension is unavailable, contact the platform — this
   migration intentionally errors loudly rather than silently degrading.

2. Adds a nullable ``embedding vector(768)`` column to
   ``vector_search_datapoints``. The dimension 768 matches
   ``Settings.vertex_embedding_dimension`` (Gemini
   ``text-embedding-004`` and Vertex ``text-embedding-005`` both produce
   768-dim vectors at this project's default). The column is nullable
   so the migration is non-blocking on existing rows — the adapter's
   upsert path backfills the column on every write and the
   ``app.jobs.backfill_pgvector_embedding`` job converts existing JSON
   ``values`` into pgvector format in a single ``UPDATE``.

3. Creates an HNSW index on ``embedding`` with the
   ``vector_cosine_ops`` operator class. HNSW is chosen over IVFFlat
   for three reasons at this scale (~1M vectors, 768 dim):

   * Recall@10 is consistently higher than IVFFlat for the same query
     time budget — important since the hybrid retrieval blend (PR #41)
     is sensitive to semantic recall.
   * No ``ANALYZE``-driven ``lists`` parameter to retune as the corpus
     grows. IVFFlat needs ``lists ≈ rows / 1000`` and a periodic
     ``REINDEX`` once the table doubles in size.
   * Insert path stays online — HNSW rebuilds incrementally, IVFFlat
     re-clusters during ``REINDEX`` (locking writes).

   ``m`` and ``ef_construction`` are left at pgvector's defaults (16 /
   64). They're tuned for 768-dim text embeddings and ``M=16`` strikes
   a good build-time / query-time / index-size trade-off up to ~10M
   rows. Operators with stricter recall targets can drop the index and
   recreate it with ``ef_construction=128`` (~3x build time, +1-2%
   recall@10).

   Query-time runtime tuning (``hnsw.ef_search``) is left to the
   application — ``PgVectorSearchAdapter`` ``SET LOCAL hnsw.ef_search =
   :ef`` per session if a higher recall target is requested.

The migration is **Postgres-only**. SQLite / other dialects encountered
during the test suite are a no-op so the same migration head works
across both environments. Tests bootstrap the schema via
``Base.metadata.create_all()`` (see ``apps/api/tests/conftest.py``) and
never run Alembic, so the no-op branch is purely defensive.

Revision ID: 0002_pgvector_native_knn
Revises: 0001_baseline
Create Date: 2026-05-25

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_pgvector_native_knn"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Keep this in sync with ``Settings.vertex_embedding_dimension``. If you
# bump the embedding model to one with a different output dimension you
# need a fresh ``ALTER TABLE ... ALTER COLUMN`` migration — pgvector
# stores the dimension in the column type and rejects mismatched inputs.
EMBEDDING_DIMENSION = 768

# HNSW index name reused by downgrade(). Keep matching the
# ``ix_<table>_<col>`` SQLAlchemy convention for grep-ability.
HNSW_INDEX_NAME = "ix_vsd_embedding_hnsw_cosine"


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect != "postgresql":
        # No-op on SQLite / others. Tests don't run Alembic and there's
        # no pgvector equivalent on SQLite — the adapter keeps the
        # Python brute-force path for non-Postgres backends.
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        f"ALTER TABLE vector_search_datapoints "
        f"ADD COLUMN IF NOT EXISTS embedding vector({EMBEDDING_DIMENSION})"
    )
    # HNSW + cosine — recall-first, online-insert-friendly. See module
    # docstring for the rationale vs IVFFlat at this scale.
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {HNSW_INDEX_NAME} "
        f"ON vector_search_datapoints USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect != "postgresql":
        return

    op.execute(f"DROP INDEX IF EXISTS {HNSW_INDEX_NAME}")
    op.execute("ALTER TABLE vector_search_datapoints DROP COLUMN IF EXISTS embedding")
    # The ``vector`` extension is deliberately left in place — other
    # tables may have started using it by the time someone runs this
    # downgrade. Dropping the extension cascades and would be lossy.
