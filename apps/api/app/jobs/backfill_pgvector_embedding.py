"""Backfill the pgvector ``embedding`` column from existing JSON ``values``.

After applying the ``0002_pgvector_native_knn`` migration, existing
``vector_search_datapoints`` rows have a populated JSON ``values``
column but a ``NULL`` ``embedding`` column. The
:class:`PgVectorSearchAdapter` query path skips rows with ``NULL``
embeddings on the native KNN fast path (``WHERE embedding IS NOT
NULL``) — running this job once after the migration moves every row
into the indexed fast path.

The job is **Postgres-only** — running it against SQLite is a no-op so
the script is safe to call unconditionally from deploy automation
without dialect-sniffing in the caller.

It is also **idempotent** — re-running the job after upserts have
already populated the column simply re-converts rows whose
``embedding`` was unset (e.g. inserted via an older adapter version)
and leaves up-to-date rows untouched (via ``WHERE embedding IS NULL``).

Usage
-----
::

    # one-off backfill after applying the pgvector migration
    python -m app.jobs.backfill_pgvector_embedding

    # restrict to a single namespace (re-running after a fresh source
    # was added)
    python -m app.jobs.backfill_pgvector_embedding --namespace jangseogak

The conversion happens entirely inside Postgres via a single
``UPDATE`` — no per-row Python round-trips, no client-side memory
spike. A 1M-row backfill at ~10K rows/sec finishes in ~100 seconds.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillReport:
    """Per-run summary surfaced to the operator + admin endpoint."""

    dialect: str
    pgvector_available: bool
    embedding_column_present: bool
    rows_updated: int
    namespace_filter: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "dialect": self.dialect,
            "pgvector_available": self.pgvector_available,
            "embedding_column_present": self.embedding_column_present,
            "rows_updated": self.rows_updated,
            "namespace_filter": self.namespace_filter,
        }


def backfill_embedding(
    session: Session,
    *,
    namespace: str | None = None,
) -> BackfillReport:
    """Convert NULL ``embedding`` cells from the JSON ``values`` column.

    Returns a :class:`BackfillReport` even when running on SQLite so
    the calling CLI / admin endpoint has consistent shape regardless
    of backend.
    """
    bind = session.bind
    dialect = bind.dialect.name if bind is not None else "unknown"
    if dialect != "postgresql":
        logger.info(
            "backfill_pgvector_embedding: dialect=%s — no-op (pgvector requires Postgres)",
            dialect,
        )
        return BackfillReport(
            dialect=dialect,
            pgvector_available=False,
            embedding_column_present=False,
            rows_updated=0,
            namespace_filter=namespace,
        )

    pgvector_available = bool(
        session.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar()
    )
    if not pgvector_available:
        logger.warning(
            "backfill_pgvector_embedding: pgvector extension not installed — "
            "run `CREATE EXTENSION vector;` or apply the 0002 migration first"
        )
        return BackfillReport(
            dialect=dialect,
            pgvector_available=False,
            embedding_column_present=False,
            rows_updated=0,
            namespace_filter=namespace,
        )

    embedding_column_present = bool(
        session.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'vector_search_datapoints' "
                "AND column_name = 'embedding'"
            )
        ).scalar()
    )
    if not embedding_column_present:
        logger.warning(
            "backfill_pgvector_embedding: vector_search_datapoints.embedding column "
            "missing — run `alembic upgrade head`"
        )
        return BackfillReport(
            dialect=dialect,
            pgvector_available=True,
            embedding_column_present=False,
            rows_updated=0,
            namespace_filter=namespace,
        )

    params: dict[str, object] = {}
    namespace_clause = ""
    if namespace is not None:
        namespace_clause = " AND namespace = :ns"
        params["ns"] = namespace
    # Cast JSON → text → vector. pgvector parses ``[0.1,0.2,...]`` (the
    # exact serialisation of a JSON list of numbers) as a vector input.
    result = session.execute(
        text(
            "UPDATE vector_search_datapoints "
            'SET embedding = ("values"::text)::vector '
            f'WHERE embedding IS NULL AND "values" IS NOT NULL{namespace_clause}'
        ),
        params,
    )
    session.commit()
    rows_updated = int(result.rowcount or 0)
    logger.info(
        "backfill_pgvector_embedding: updated %d row(s) (namespace=%s)",
        rows_updated,
        namespace or "*",
    )
    return BackfillReport(
        dialect=dialect,
        pgvector_available=True,
        embedding_column_present=True,
        rows_updated=rows_updated,
        namespace_filter=namespace,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill vector_search_datapoints.embedding from JSON values.",
    )
    parser.add_argument(
        "--namespace",
        default=None,
        help="Restrict the backfill to one heritage source namespace.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    session = SessionLocal()
    try:
        report = backfill_embedding(session, namespace=args.namespace)
    finally:
        session.close()

    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI entry
    sys.exit(main())
