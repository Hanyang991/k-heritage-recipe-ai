"""Tests for :class:`PgVectorSearchAdapter` — Postgres-backed vector store.

Runs against an in-memory SQLite engine (StaticPool) per test so the
adapter can be exercised without a real Postgres instance. The schema
is portable JSON columns only — production Postgres deployments use
the same ORM mapping.
"""

from __future__ import annotations

import math

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.vector_search_datapoint import VectorSearchDatapoint
from app.services.vector_search import get_vector_search_adapter
from app.services.vector_search.base import (
    VectorDatapoint,
    VectorIndexNotConfiguredError,
)
from app.services.vector_search.mock import MockVectorSearchAdapter
from app.services.vector_search.pgvector import PgVectorSearchAdapter


def _unit(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _dp(
    id_: str,
    values: list[float],
    *,
    restricts: dict[str, list[str]] | None = None,
    metadata: dict[str, str] | None = None,
) -> VectorDatapoint:
    return VectorDatapoint(
        datapoint_id=id_,
        values=values,
        restricts=restricts or {},
        metadata=metadata or {},
    )


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


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_pgvector_requires_at_least_one_namespace(session_factory) -> None:
    with pytest.raises(ValueError, match="at least one namespace"):
        PgVectorSearchAdapter(session_factory=session_factory, namespaces=[])


def test_pgvector_known_namespaces_preserves_order(session_factory) -> None:
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak", "koreanstudies", "nlk"],
    )
    assert a.known_namespaces() == ["jangseogak", "koreanstudies", "nlk"]


# ---------------------------------------------------------------------------
# Upsert / query happy path
# ---------------------------------------------------------------------------


def test_pgvector_upsert_and_query_isolated_per_namespace(session_factory) -> None:
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak", "nlk"],
    )
    js_vec = _unit([1.0, 0.0, 0.0])
    nlk_vec = _unit([0.0, 1.0, 0.0])
    a.upsert("jangseogak", [_dp("jsg:1", js_vec)])
    a.upsert("nlk", [_dp("nlk:1", nlk_vec)])

    jsg_results = a.query("jangseogak", js_vec, top_k=5)
    assert [m.datapoint_id for m in jsg_results] == ["jsg:1"]
    assert math.isclose(jsg_results[0].score, 1.0, abs_tol=1e-9)

    nlk_results = a.query("nlk", js_vec, top_k=5)
    assert [m.datapoint_id for m in nlk_results] == ["nlk:1"]
    assert nlk_results[0].score == 0.0


def test_pgvector_upsert_is_idempotent_by_datapoint_id(session_factory) -> None:
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak"],
    )
    a.upsert("jangseogak", [_dp("jsg:1", _unit([1.0, 0.0]))])
    a.upsert("jangseogak", [_dp("jsg:1", _unit([0.0, 1.0]))])

    # Only one row exists for that (namespace, datapoint_id) — second
    # upsert replaced the first.
    session: Session = session_factory()
    try:
        count = session.query(VectorSearchDatapoint).count()
    finally:
        session.close()
    assert count == 1

    # The query should return the new vector's similarity, not the old.
    results = a.query("jangseogak", _unit([0.0, 1.0]), top_k=5)
    assert len(results) == 1
    assert math.isclose(results[0].score, 1.0, abs_tol=1e-9)


def test_pgvector_upsert_empty_batch_is_noop(session_factory) -> None:
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak"],
    )
    a.upsert("jangseogak", [])  # Should not raise, should not insert anything.
    session: Session = session_factory()
    try:
        assert session.query(VectorSearchDatapoint).count() == 0
    finally:
        session.close()


def test_pgvector_query_empty_namespace_returns_empty(session_factory) -> None:
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak"],
    )
    assert a.query("jangseogak", [1.0, 0.0, 0.0], top_k=10) == []


def test_pgvector_query_top_k_zero_returns_empty(session_factory) -> None:
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak"],
    )
    a.upsert("jangseogak", [_dp("jsg:1", _unit([1.0, 0.0]))])
    assert a.query("jangseogak", [1.0, 0.0], top_k=0) == []


def test_pgvector_query_top_k_clips_results(session_factory) -> None:
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak"],
    )
    a.upsert(
        "jangseogak",
        [
            _dp("jsg:1", _unit([1.0, 0.0])),
            _dp("jsg:2", _unit([0.9, 0.1])),
            _dp("jsg:3", _unit([0.0, 1.0])),
        ],
    )
    out = a.query("jangseogak", _unit([1.0, 0.0]), top_k=2)
    assert len(out) == 2
    # Highest similarity first.
    assert [m.datapoint_id for m in out] == ["jsg:1", "jsg:2"]


def test_pgvector_query_returns_metadata(session_factory) -> None:
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak"],
    )
    metadata = {"title": "음식디미방", "institution": "jangseogak", "year": "1670"}
    a.upsert("jangseogak", [_dp("jsg:1", _unit([1.0, 0.0]), metadata=metadata)])
    out = a.query("jangseogak", _unit([1.0, 0.0]), top_k=1)
    assert out[0].metadata == metadata


def test_pgvector_query_results_sort_stable_on_ties(session_factory) -> None:
    """Ties in score break by ascending datapoint_id (matches mock contract)."""
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak"],
    )
    # Three identical vectors → identical scores → stable order on id.
    a.upsert(
        "jangseogak",
        [
            _dp("jsg:b", _unit([1.0, 0.0])),
            _dp("jsg:a", _unit([1.0, 0.0])),
            _dp("jsg:c", _unit([1.0, 0.0])),
        ],
    )
    out = a.query("jangseogak", _unit([1.0, 0.0]), top_k=3)
    assert [m.datapoint_id for m in out] == ["jsg:a", "jsg:b", "jsg:c"]


# ---------------------------------------------------------------------------
# Restricts (Vertex-AI-compatible AND-of-ORs filter)
# ---------------------------------------------------------------------------


def test_pgvector_restricts_filter_keeps_matching_rows(session_factory) -> None:
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak"],
    )
    a.upsert(
        "jangseogak",
        [
            _dp(
                "jsg:1",
                _unit([1.0, 0.0]),
                restricts={"period": ["조선전기"]},
            ),
            _dp(
                "jsg:2",
                _unit([0.9, 0.1]),
                restricts={"period": ["조선후기"]},
            ),
        ],
    )
    # Restricting to 조선전기 filters out jsg:2.
    out = a.query(
        "jangseogak",
        _unit([1.0, 0.0]),
        top_k=10,
        restricts={"period": ["조선전기"]},
    )
    assert [m.datapoint_id for m in out] == ["jsg:1"]


def test_pgvector_restricts_filter_drops_rows_missing_key(session_factory) -> None:
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak"],
    )
    a.upsert(
        "jangseogak",
        [
            _dp("jsg:1", _unit([1.0, 0.0]), restricts={"period": ["조선전기"]}),
            _dp("jsg:2", _unit([0.9, 0.1])),  # no period restrict
        ],
    )
    out = a.query(
        "jangseogak",
        _unit([1.0, 0.0]),
        top_k=10,
        restricts={"period": ["조선전기"]},
    )
    assert [m.datapoint_id for m in out] == ["jsg:1"]


def test_pgvector_restricts_filter_supports_or_within_key(session_factory) -> None:
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak"],
    )
    a.upsert(
        "jangseogak",
        [
            _dp("jsg:1", _unit([1.0, 0.0]), restricts={"period": ["조선전기"]}),
            _dp("jsg:2", _unit([0.9, 0.1]), restricts={"period": ["조선후기"]}),
            _dp("jsg:3", _unit([0.8, 0.2]), restricts={"period": ["근대"]}),
        ],
    )
    out = a.query(
        "jangseogak",
        _unit([1.0, 0.0]),
        top_k=10,
        restricts={"period": ["조선전기", "조선후기"]},
    )
    assert sorted(m.datapoint_id for m in out) == ["jsg:1", "jsg:2"]


def test_pgvector_restricts_empty_dict_matches_everything(session_factory) -> None:
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak"],
    )
    a.upsert(
        "jangseogak",
        [
            _dp("jsg:1", _unit([1.0, 0.0])),
            _dp("jsg:2", _unit([0.9, 0.1])),
        ],
    )
    out = a.query("jangseogak", _unit([1.0, 0.0]), top_k=10, restricts={})
    assert len(out) == 2


# ---------------------------------------------------------------------------
# Unknown namespace
# ---------------------------------------------------------------------------


def test_pgvector_query_unknown_namespace_raises(session_factory) -> None:
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak"],
    )
    with pytest.raises(VectorIndexNotConfiguredError):
        a.query("unknown", [1.0, 0.0], top_k=1)


def test_pgvector_upsert_unknown_namespace_raises(session_factory) -> None:
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak"],
    )
    with pytest.raises(VectorIndexNotConfiguredError):
        a.upsert("unknown", [_dp("x:1", [1.0, 0.0])])


# ---------------------------------------------------------------------------
# Rollback on commit failure
# ---------------------------------------------------------------------------


def test_pgvector_upsert_rolls_back_on_error(session_factory, monkeypatch) -> None:
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak"],
    )
    # First upsert succeeds, second triggers an error before commit.
    a.upsert("jangseogak", [_dp("jsg:1", _unit([1.0, 0.0]))])

    original_commit = Session.commit

    def boom(self) -> None:
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(Session, "commit", boom)
    with pytest.raises(RuntimeError, match="simulated commit failure"):
        a.upsert("jangseogak", [_dp("jsg:2", _unit([0.0, 1.0]))])

    # After rollback, jsg:2 must not be persisted.
    monkeypatch.setattr(Session, "commit", original_commit)
    out = a.query("jangseogak", _unit([0.0, 1.0]), top_k=5)
    assert [m.datapoint_id for m in out] == ["jsg:1"]


# ---------------------------------------------------------------------------
# Factory routing
# ---------------------------------------------------------------------------


def test_factory_returns_mock_when_provider_is_mock(monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    get_vector_search_adapter.cache_clear()
    monkeypatch.setenv("VECTOR_SEARCH_PROVIDER", "mock")
    try:
        adapter = get_vector_search_adapter()
    finally:
        get_settings.cache_clear()
        get_vector_search_adapter.cache_clear()
    assert isinstance(adapter, MockVectorSearchAdapter)


def test_factory_returns_pgvector_when_configured(monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    get_vector_search_adapter.cache_clear()
    monkeypatch.setenv("VECTOR_SEARCH_PROVIDER", "pgvector")
    try:
        adapter = get_vector_search_adapter()
    finally:
        get_settings.cache_clear()
        get_vector_search_adapter.cache_clear()
    assert isinstance(adapter, PgVectorSearchAdapter)


# ---------------------------------------------------------------------------
# Native KNN backend selection
# ---------------------------------------------------------------------------


def test_should_use_native_knn_returns_false_on_sqlite(session_factory) -> None:
    """SQLite is the test default — the adapter must never try to run
    pgvector-specific SQL against it.
    """
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak"],
    )
    session = session_factory()
    try:
        assert a._should_use_native_knn(session) is False
    finally:
        session.close()


def test_should_use_native_knn_returns_false_when_disabled(session_factory) -> None:
    """``native_knn=False`` short-circuits the probe regardless of dialect."""
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak"],
        native_knn=False,
    )
    session = session_factory()
    try:
        assert a._should_use_native_knn(session) is False
    finally:
        session.close()


def test_query_on_sqlite_uses_python_path_unchanged(session_factory) -> None:
    """End-to-end smoke test: with the default ``native_knn=True`` on
    SQLite the adapter falls back to the Python brute-force path and
    produces identical results to the pre-pgvector-PR behaviour.
    """
    a = PgVectorSearchAdapter(
        session_factory=session_factory,
        namespaces=["jangseogak"],
    )
    a.upsert(
        "jangseogak",
        [
            _dp("jsg:1", _unit([1.0, 0.0])),
            _dp("jsg:2", _unit([0.9, 0.1])),
            _dp("jsg:3", _unit([0.0, 1.0])),
        ],
    )
    out = a.query("jangseogak", _unit([1.0, 0.0]), top_k=3)
    assert [m.datapoint_id for m in out] == ["jsg:1", "jsg:2", "jsg:3"]
    # Native fast path was never engaged on SQLite — the cache stays
    # ``None`` (we never even probed because the dialect check failed
    # first).
    assert a._pgvector_ready is None


def test_factory_passes_native_knn_setting(monkeypatch) -> None:
    """``settings.pgvector_native_knn=False`` flows through the factory
    into the adapter so operators can disable the fast path without
    changing code.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    get_vector_search_adapter.cache_clear()
    monkeypatch.setenv("VECTOR_SEARCH_PROVIDER", "pgvector")
    monkeypatch.setenv("PGVECTOR_NATIVE_KNN", "false")
    try:
        adapter = get_vector_search_adapter()
    finally:
        get_settings.cache_clear()
        get_vector_search_adapter.cache_clear()
    assert isinstance(adapter, PgVectorSearchAdapter)
    assert adapter._native_knn_enabled is False
