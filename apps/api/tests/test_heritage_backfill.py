"""Tests for ``HeritageBackfillRunner`` and ``run_heritage_backfill``."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest

from app.services.embeddings.mock import MockEmbeddingAdapter
from app.services.heritage.base import DocumentMatch, HeritageAdapter, HeritageDoc
from app.services.vector_search.backfill import (
    DEFAULT_BACKFILL_QUERIES,
    BackfillReport,
    HeritageBackfillRunner,
    run_heritage_backfill,
)
from app.services.vector_search.indexer import HeritageIndexer
from app.services.vector_search.mock import MockVectorSearchAdapter


def _doc(institution: str, external_id: str, title: str = "") -> HeritageDoc:
    return HeritageDoc(
        external_id=external_id,
        title=title or f"{institution}:{external_id}",
        institution=institution,
        region="전국",
        period="조선후기",
        category="고문서",
        year=1700,
        original_text="원문",
        summary="요약",
    )


class _ScriptedHeritageAdapter(HeritageAdapter):
    """Adapter whose ``search`` returns a per-query script.

    ``scripts`` maps query strings → list of (institution, external_id)
    pairs. Unknown queries return empty. ``failures`` is a set of
    queries that should raise instead of returning matches.
    """

    def __init__(
        self,
        scripts: dict[str, list[tuple[str, str]]],
        *,
        failures: set[str] | None = None,
    ) -> None:
        self._scripts = scripts
        self._failures = failures or set()
        self.calls: list[tuple[str, int]] = []

    def search(
        self,
        keyword: str,
        region: str | None = None,
        period: str | None = None,
        limit: int = 10,
    ) -> list[DocumentMatch]:
        self.calls.append((keyword, limit))
        if keyword in self._failures:
            raise RuntimeError(f"transient failure for query={keyword!r}")
        return [
            DocumentMatch(document=_doc(inst, eid), match_score=1.0)
            for inst, eid in self._scripts.get(keyword, [])
        ]

    def list_seeded(self) -> list[HeritageDoc]:  # pragma: no cover - unused
        return []


def _make_indexer(namespaces: list[str]) -> tuple[HeritageIndexer, MockVectorSearchAdapter]:
    store = MockVectorSearchAdapter(namespaces=namespaces)
    indexer = HeritageIndexer(embedder=MockEmbeddingAdapter(), vector_store=store)
    return indexer, store


# ----- Construction validation ----------------------------------------


def test_runner_rejects_non_positive_per_query_limit() -> None:
    indexer, _ = _make_indexer(["jangseogak"])
    with pytest.raises(ValueError, match="per_query_limit"):
        HeritageBackfillRunner(
            heritage_adapter=_ScriptedHeritageAdapter({}),
            indexer=indexer,
            per_query_limit=0,
            queries=["x"],
        )


def test_runner_rejects_non_positive_batch_size() -> None:
    indexer, _ = _make_indexer(["jangseogak"])
    with pytest.raises(ValueError, match="batch_size"):
        HeritageBackfillRunner(
            heritage_adapter=_ScriptedHeritageAdapter({}),
            indexer=indexer,
            batch_size=0,
            queries=["x"],
        )


def test_runner_rejects_empty_query_pool() -> None:
    indexer, _ = _make_indexer(["jangseogak"])
    with pytest.raises(ValueError, match="non-empty query"):
        HeritageBackfillRunner(
            heritage_adapter=_ScriptedHeritageAdapter({}),
            indexer=indexer,
            queries=["", "   "],
        )


def test_runner_default_queries_are_the_curated_pool() -> None:
    indexer, _ = _make_indexer(["jangseogak"])
    runner = HeritageBackfillRunner(
        heritage_adapter=_ScriptedHeritageAdapter({}),
        indexer=indexer,
    )
    assert runner.queries == list(DEFAULT_BACKFILL_QUERIES)


def test_default_pool_is_non_empty_and_unique() -> None:
    pool = list(DEFAULT_BACKFILL_QUERIES)
    assert len(pool) >= 10
    assert len(pool) == len(set(pool))  # no duplicates


# ----- Happy path -----------------------------------------------------


def test_run_walks_queries_dedupes_and_upserts() -> None:
    indexer, store = _make_indexer(["jangseogak", "koreanstudies"])
    adapter = _ScriptedHeritageAdapter(
        {
            "음식": [("jangseogak", "a"), ("koreanstudies", "k1")],
            "의궤": [("jangseogak", "a"), ("jangseogak", "b")],  # 'a' is dup
            "떡": [("koreanstudies", "k2")],
        }
    )
    runner = HeritageBackfillRunner(
        heritage_adapter=adapter,
        indexer=indexer,
        queries=["음식", "의궤", "떡"],
    )
    report = runner.run()
    assert report.queries_attempted == 3
    assert report.queries_succeeded == 3
    assert report.queries_failed == {}
    # 'a' is shared between 음식 and 의궤; should only count once.
    assert report.unique_docs_collected == 4
    assert report.docs_per_source == {"jangseogak": 2, "koreanstudies": 2}
    assert report.index_result.upserted == {"jangseogak": 2, "koreanstudies": 2}
    assert report.total_upserted == 4
    # MockVectorSearchAdapter actually stores them.
    assert sorted(store._store["jangseogak"].keys()) == ["jangseogak:a", "jangseogak:b"]
    assert sorted(store._store["koreanstudies"].keys()) == [
        "koreanstudies:k1",
        "koreanstudies:k2",
    ]


def test_run_passes_per_query_limit_through_to_adapter() -> None:
    indexer, _ = _make_indexer(["jangseogak"])
    adapter = _ScriptedHeritageAdapter({"q": [("jangseogak", "a")]})
    runner = HeritageBackfillRunner(
        heritage_adapter=adapter,
        indexer=indexer,
        queries=["q"],
        per_query_limit=37,
    )
    runner.run()
    assert adapter.calls == [("q", 37)]


def test_run_chunks_docs_per_batch_size() -> None:
    indexer, _ = _make_indexer(["jangseogak"])
    adapter = _ScriptedHeritageAdapter(
        {"q": [("jangseogak", f"d{i}") for i in range(7)]}
    )
    calls: list[int] = []
    real_index = indexer.index_documents

    def spy(batch):  # type: ignore[no-untyped-def]
        calls.append(len(batch))
        return real_index(batch)

    indexer.index_documents = spy  # type: ignore[method-assign]
    runner = HeritageBackfillRunner(
        heritage_adapter=adapter,
        indexer=indexer,
        queries=["q"],
        batch_size=3,
    )
    report = runner.run()
    assert calls == [3, 3, 1]
    assert report.total_upserted == 7


# ----- Resilience -----------------------------------------------------


def test_per_query_failures_are_isolated() -> None:
    indexer, _ = _make_indexer(["jangseogak"])
    adapter = _ScriptedHeritageAdapter(
        {"good": [("jangseogak", "a")]},
        failures={"bad"},
    )
    runner = HeritageBackfillRunner(
        heritage_adapter=adapter,
        indexer=indexer,
        queries=["bad", "good"],
    )
    report = runner.run()
    assert report.queries_attempted == 2
    assert report.queries_succeeded == 1
    assert "bad" in report.queries_failed
    assert "transient failure" in report.queries_failed["bad"]
    # Good query's docs still indexed.
    assert report.total_upserted == 1


def test_unknown_namespace_docs_are_skipped_via_indexer() -> None:
    # Indexer only knows jangseogak; koreanstudies docs should land in skipped_unknown_namespace.
    indexer, _ = _make_indexer(["jangseogak"])
    adapter = _ScriptedHeritageAdapter(
        {"q": [("jangseogak", "a"), ("koreanstudies", "k1")]}
    )
    runner = HeritageBackfillRunner(
        heritage_adapter=adapter,
        indexer=indexer,
        queries=["q"],
    )
    report = runner.run()
    assert report.unique_docs_collected == 2  # collect happens before indexer routing
    assert report.docs_per_source == {"jangseogak": 1, "koreanstudies": 1}
    assert report.index_result.upserted == {"jangseogak": 1}
    assert report.index_result.skipped_unknown_namespace == {"koreanstudies": 1}


def test_all_queries_failing_yields_empty_report() -> None:
    indexer, _ = _make_indexer(["jangseogak"])
    adapter = _ScriptedHeritageAdapter({}, failures={"a", "b"})
    runner = HeritageBackfillRunner(
        heritage_adapter=adapter,
        indexer=indexer,
        queries=["a", "b"],
    )
    report = runner.run()
    assert report.queries_attempted == 2
    assert report.queries_succeeded == 0
    assert set(report.queries_failed.keys()) == {"a", "b"}
    assert report.unique_docs_collected == 0
    assert report.total_upserted == 0


def test_idempotent_rerun_does_not_duplicate_in_store() -> None:
    indexer, store = _make_indexer(["jangseogak"])
    adapter = _ScriptedHeritageAdapter({"q": [("jangseogak", "a"), ("jangseogak", "b")]})
    runner = HeritageBackfillRunner(
        heritage_adapter=adapter,
        indexer=indexer,
        queries=["q"],
    )
    runner.run()
    runner.run()
    assert sorted(store._store["jangseogak"].keys()) == ["jangseogak:a", "jangseogak:b"]


# ----- as_dict + report shape ----------------------------------------


def test_report_as_dict_shape() -> None:
    report = BackfillReport()
    report.queries_attempted = 3
    report.queries_succeeded = 2
    report.queries_failed = {"x": "boom"}
    report.unique_docs_collected = 5
    report.docs_per_source = {"jangseogak": 3, "koreanstudies": 2}
    report.index_result.upserted = {"jangseogak": 3, "koreanstudies": 2}
    report.index_result.errored = {}
    report.index_result.skipped_unknown_namespace = {}
    snapshot = report.as_dict()
    assert snapshot["queries_attempted"] == 3
    assert snapshot["queries_succeeded"] == 2
    assert snapshot["queries_failed"] == {"x": "boom"}
    assert snapshot["unique_docs_collected"] == 5
    assert snapshot["docs_per_source"] == {"jangseogak": 3, "koreanstudies": 2}
    assert snapshot["upserted_per_namespace"] == {"jangseogak": 3, "koreanstudies": 2}
    assert snapshot["errored_per_namespace"] == {}
    assert snapshot["skipped_unknown_namespace"] == {}
    assert snapshot["total_upserted"] == 5


# ----- High-level run_heritage_backfill() wiring ----------------------


@pytest.fixture
def _restore_settings_cache() -> Iterator[None]:
    """Bust the ``get_settings`` lru_cache around tests that override env vars."""
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_run_heritage_backfill_wires_settings_through(
    monkeypatch: pytest.MonkeyPatch,
    _restore_settings_cache: None,
) -> None:
    """Confirm ``run_heritage_backfill`` builds the runner from settings."""
    monkeypatch.setenv("HERITAGE_BACKFILL_QUERIES", "alpha,beta")
    monkeypatch.setenv("HERITAGE_BACKFILL_PER_QUERY_LIMIT", "7")
    monkeypatch.setenv("HERITAGE_BACKFILL_BATCH_SIZE", "11")

    adapter = _ScriptedHeritageAdapter(
        {"alpha": [("jangseogak", "a")], "beta": [("jangseogak", "b")]}
    )
    indexer, _ = _make_indexer(["jangseogak"])

    captured: dict[str, Any] = {}
    real_init = HeritageBackfillRunner.__init__

    def spy_init(self, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        real_init(self, **kwargs)

    with (
        patch(
            "app.services.heritage.get_keyword_heritage_adapter",
            return_value=adapter,
        ),
        patch(
            "app.services.embeddings.get_embedding_adapter",
            return_value=MockEmbeddingAdapter(),
        ),
        patch(
            "app.services.vector_search.get_vector_search_adapter",
            return_value=indexer._vector_store,  # type: ignore[attr-defined]
        ),
        patch.object(HeritageBackfillRunner, "__init__", spy_init),
    ):
        report = run_heritage_backfill()

    # Settings flowed into the runner.
    assert captured["queries"] == ["alpha", "beta"]
    assert captured["per_query_limit"] == 7
    assert captured["batch_size"] == 11
    # End-to-end happy path still produced upserts.
    assert report.queries_succeeded == 2
    assert report.unique_docs_collected == 2


def test_run_heritage_backfill_explicit_args_override_settings(
    monkeypatch: pytest.MonkeyPatch,
    _restore_settings_cache: None,
) -> None:
    monkeypatch.setenv("HERITAGE_BACKFILL_QUERIES", "from_env")
    monkeypatch.setenv("HERITAGE_BACKFILL_PER_QUERY_LIMIT", "5")
    monkeypatch.setenv("HERITAGE_BACKFILL_BATCH_SIZE", "5")

    adapter = _ScriptedHeritageAdapter({"override": [("jangseogak", "z")]})
    indexer, _ = _make_indexer(["jangseogak"])

    captured: dict[str, Any] = {}
    real_init = HeritageBackfillRunner.__init__

    def spy_init(self, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        real_init(self, **kwargs)

    with (
        patch(
            "app.services.heritage.get_keyword_heritage_adapter",
            return_value=adapter,
        ),
        patch(
            "app.services.embeddings.get_embedding_adapter",
            return_value=MockEmbeddingAdapter(),
        ),
        patch(
            "app.services.vector_search.get_vector_search_adapter",
            return_value=indexer._vector_store,  # type: ignore[attr-defined]
        ),
        patch.object(HeritageBackfillRunner, "__init__", spy_init),
    ):
        run_heritage_backfill(
            queries=["override"], per_query_limit=99, batch_size=42
        )

    assert captured["queries"] == ["override"]
    assert captured["per_query_limit"] == 99
    assert captured["batch_size"] == 42
