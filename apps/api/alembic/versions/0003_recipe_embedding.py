"""recipe embedding storage — JSON ``embedding_values`` + pgvector mirror.

Mirrors the storage pattern set by ``0002_pgvector_native_knn`` but on the
``recipes`` table directly (instead of the
``vector_search_datapoints`` side-table). Rationale for keeping the
embedding on ``recipes`` rather than spinning up a new namespace inside
``vector_search_datapoints``:

* Recipes have row-level ownership + status visibility (``user_id``,
  ``status``) which the heritage vector pipeline does not. Co-locating
  the embedding with the visibility columns lets the related-recipes
  query stay in a single ``SELECT … FROM recipes`` with the same
  visibility ``WHERE`` clause the tag-based path uses.
* Recipes are mutated by users (rating, status transitions, deletion)
  — when a row goes away the embedding needs to go away in the same
  transaction. The FK / cascade story is trivial when the column lives
  on the row.
* Heritage docs are read-mostly and shared; recipes are write-heavy
  and per-user. Different access patterns suggest separate physical
  storage.

The migration:

1. Adds a nullable ``embedding_values`` JSON column to ``recipes`` so
   the same column is present on every dialect — SQLite (tests) reads
   the JSON; Postgres can keep both JSON + native ``vector`` in sync.
2. On Postgres only: adds a nullable ``embedding vector(N)`` column +
   HNSW cosine index. ``N`` matches
   ``Settings.vertex_embedding_dimension`` (Gemini text-embedding-004
   and Vertex text-embedding-005 both produce 768-dim vectors). The
   ``vector`` extension is assumed already installed by the previous
   migration (``0002_pgvector_native_knn``).
3. Column is nullable so the migration is non-blocking on existing
   recipes. ``app.jobs.backfill_recipe_embeddings`` populates the
   column lazily for back-catalogue rows; the recipe-generate hook
   populates it for fresh rows synchronously.

SQLite / other dialects are a no-op on the pgvector half — same
defensive pattern as ``0002_pgvector_native_knn``.

Revision ID: 0003_recipe_embedding
Revises: 0002_pgvector_native_knn
Create Date: 2026-05-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_recipe_embedding"
down_revision: str | None = "0002_pgvector_native_knn"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Keep in sync with ``Settings.vertex_embedding_dimension``. Bumping the
# embedding model to a different output dimension requires a fresh
# ``ALTER TABLE`` migration — pgvector pins the dimension in the column
# type and rejects mismatched inputs at write time.
EMBEDDING_DIMENSION = 768

HNSW_INDEX_NAME = "ix_recipes_embedding_hnsw_cosine"


def upgrade() -> None:
    # Portable JSON column — Postgres uses ``jsonb`` via SQLAlchemy's
    # JSON type, SQLite uses TEXT-as-JSON. Nullable so existing rows
    # don't need a backfill before the migration can finish.
    op.add_column(
        "recipes",
        sa.Column("embedding_values", sa.JSON(), nullable=True),
    )

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite (tests, local dev) stops here. The vector_search
        # adapter's Python brute-force path covers SQLite already; the
        # recommendation service mirrors the same dialect-aware
        # branch at query time.
        return

    op.execute(
        f"ALTER TABLE recipes "
        f"ADD COLUMN IF NOT EXISTS embedding vector({EMBEDDING_DIMENSION})"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {HNSW_INDEX_NAME} "
        f"ON recipes USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"DROP INDEX IF EXISTS {HNSW_INDEX_NAME}")
        op.execute("ALTER TABLE recipes DROP COLUMN IF EXISTS embedding")
    op.drop_column("recipes", "embedding_values")
