"""Tests for the ``backfill_pgvector_embedding`` job.

The job's heavy lifting is one Postgres-only ``UPDATE`` casting the
JSON ``values`` column into ``vector(N)`` cells. We can't exercise that
SQL path against SQLite (no pgvector extension), so the unit tests
focus on the dialect-detection guard rails that keep the script safe
to call from deploy automation regardless of backend.

The Postgres branch is exercised by the live integration check in
``docker compose up`` (see ``docker-compose.yml`` API command) — the
operator-visible report shape stays consistent across both branches.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.jobs.backfill_pgvector_embedding import BackfillReport, backfill_embedding


@pytest.fixture()
def session_factory():
    """Fresh in-memory SQLite DB + session factory per test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    yield factory
    engine.dispose()


def test_backfill_is_noop_on_sqlite(session_factory) -> None:
    """SQLite has no pgvector extension. The job must return a
    well-formed report rather than crashing, so deploy automation
    can call it unconditionally on the test stack.
    """
    session = session_factory()
    try:
        report = backfill_embedding(session)
    finally:
        session.close()

    assert isinstance(report, BackfillReport)
    assert report.dialect == "sqlite"
    assert report.pgvector_available is False
    assert report.embedding_column_present is False
    assert report.rows_updated == 0
    assert report.namespace_filter is None


def test_backfill_report_serialises_to_plain_dict(session_factory) -> None:
    """The CLI prints ``report.as_dict()`` via ``json.dumps`` —
    confirm the result is a vanilla mapping of primitives so JSON
    encoding never fails on deploy.
    """
    session = session_factory()
    try:
        report = backfill_embedding(session, namespace="jangseogak")
    finally:
        session.close()

    data = report.as_dict()
    assert data == {
        "dialect": "sqlite",
        "pgvector_available": False,
        "embedding_column_present": False,
        "rows_updated": 0,
        "namespace_filter": "jangseogak",
    }
