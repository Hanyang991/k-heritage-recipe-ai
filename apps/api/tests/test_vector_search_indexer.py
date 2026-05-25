"""Tests for :class:`HeritageIndexer` — namespace-routed embed + upsert/query."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.embeddings.mock import MockEmbeddingAdapter
from app.services.heritage.base import HeritageDoc
from app.services.vector_search.base import (
    VectorIndexNotConfiguredError,
    VectorMatch,
)
from app.services.vector_search.indexer import (
    CrossSourceMatch,
    HeritageIndexer,
    heritage_doc_id,
    heritage_doc_metadata,
    heritage_doc_restricts,
    heritage_doc_text,
)
from app.services.vector_search.mock import MockVectorSearchAdapter


def _doc(
    *,
    external_id: str = "1",
    title: str = "음식디미방",
    institution: str = "jangseogak",
    region: str = "충청",
    period: str = "조선후기",
    year: int = 1670,
    category: str = "고문헌",
    original_text: str = "",
    summary: str = "",
) -> HeritageDoc:
    return HeritageDoc(
        external_id=external_id,
        title=title,
        institution=institution,
        region=region,
        period=period,
        category=category,
        year=year,
        original_text=original_text,
        summary=summary,
    )


_DEFAULT_NAMESPACES = ("jangseogak", "koreanstudies", "nlk", "gihohak")


def _indexer(
    namespaces: tuple[str, ...] | list[str] = _DEFAULT_NAMESPACES,
    *,
    dimension: int = 32,
    allowed_namespaces: list[str] | None = None,
) -> tuple[HeritageIndexer, MockVectorSearchAdapter, MockEmbeddingAdapter]:
    embedder = MockEmbeddingAdapter(dimension=dimension)
    store = MockVectorSearchAdapter(namespaces=list(namespaces))
    indexer = HeritageIndexer(
        embedder=embedder,
        vector_store=store,
        allowed_namespaces=allowed_namespaces,
    )
    return indexer, store, embedder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_heritage_doc_id_uses_institution_and_external_id() -> None:
    doc = _doc(institution="jangseogak", external_id="ABC123")
    assert heritage_doc_id(doc) == "jangseogak:ABC123"


def test_heritage_doc_text_concatenates_signal_fields() -> None:
    doc = _doc(
        title="음식디미방",
        summary="조선 후기 한글 음식 조리서",
        original_text="원문...",
        period="조선후기",
        region="충청",
        category="고문헌",
    )
    text = heritage_doc_text(doc)
    assert "음식디미방" in text
    assert "조선 후기 한글 음식 조리서" in text
    assert "시대: 조선후기" in text
    assert "지역: 충청" in text
    assert "분류: 고문헌" in text


def test_heritage_doc_text_truncates_long_original_text() -> None:
    long_text = "가" * 5000
    doc = _doc(original_text=long_text)
    text = heritage_doc_text(doc)
    assert long_text[:2000] in text
    assert long_text[2001:] not in text


def test_heritage_doc_restricts_omits_empty_fields() -> None:
    doc = _doc(region="", period="조선후기", category="")
    restricts = heritage_doc_restricts(doc)
    assert restricts == {"period": ["조선후기"]}


def test_heritage_doc_metadata_includes_canonical_fields() -> None:
    doc = _doc(year=1670)
    md = heritage_doc_metadata(doc)
    assert md["title"] == "음식디미방"
    assert md["institution"] == "jangseogak"
    assert md["year"] == "1670"
    assert md["period"] == "조선후기"


def test_heritage_doc_metadata_handles_none_year() -> None:
    doc = _doc(year=None)
    md = heritage_doc_metadata(doc)
    assert "year" not in md


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_indexer_defaults_allowed_to_store_namespaces() -> None:
    indexer, _, _ = _indexer(namespaces=["jangseogak", "nlk"])
    assert indexer.allowed_namespaces == ["jangseogak", "nlk"]


def test_indexer_respects_explicit_allowed_list() -> None:
    indexer, _, _ = _indexer(
        namespaces=["jangseogak", "nlk"],
        allowed_namespaces=["jangseogak"],
    )
    assert indexer.allowed_namespaces == ["jangseogak"]


def test_indexer_rejects_empty_allowed_namespaces() -> None:
    embedder = MockEmbeddingAdapter(dimension=8)
    store = MockVectorSearchAdapter(namespaces=["jangseogak"])
    with pytest.raises(ValueError, match="at least one allowed namespace"):
        HeritageIndexer(embedder=embedder, vector_store=store, allowed_namespaces=[])


# ---------------------------------------------------------------------------
# index_documents — routes per source
# ---------------------------------------------------------------------------


def test_index_documents_routes_each_doc_to_its_source_namespace() -> None:
    indexer, store, _ = _indexer()
    docs = [
        _doc(institution="jangseogak", external_id="A"),
        _doc(institution="koreanstudies", external_id="B"),
        _doc(institution="nlk", external_id="C"),
        _doc(institution="jangseogak", external_id="D"),
    ]
    result = indexer.index_documents(docs)
    assert result.upserted == {"jangseogak": 2, "koreanstudies": 1, "nlk": 1}
    assert result.total_upserted == 4

    # Each namespace ended up with its own docs only.
    jsg_results = store.query("jangseogak", [1.0] * 32, top_k=10)
    assert sorted(m.datapoint_id for m in jsg_results) == [
        "jangseogak:A",
        "jangseogak:D",
    ]
    nlk_results = store.query("nlk", [1.0] * 32, top_k=10)
    assert [m.datapoint_id for m in nlk_results] == ["nlk:C"]


def test_index_documents_skips_unknown_namespaces() -> None:
    indexer, store, _ = _indexer(
        namespaces=["jangseogak"],
        allowed_namespaces=["jangseogak"],
    )
    docs = [
        _doc(institution="jangseogak", external_id="A"),
        # ``nfm`` isn't in allowed_namespaces — should be skipped, not raised.
        _doc(institution="nfm", external_id="X"),
    ]
    result = indexer.index_documents(docs)
    assert result.upserted == {"jangseogak": 1}
    assert result.skipped_unknown_namespace == {"nfm": 1}
    assert result.errored == {}


def test_index_documents_isolates_per_namespace_failures() -> None:
    # Build a vector store that succeeds for jangseogak but fails for nlk.
    embedder = MockEmbeddingAdapter(dimension=16)
    store = MagicMock()
    store.known_namespaces.return_value = ["jangseogak", "nlk"]
    store.upsert.side_effect = lambda namespace, datapoints: (
        None if namespace == "jangseogak" else (_ for _ in ()).throw(RuntimeError("vertex down"))
    )
    indexer = HeritageIndexer(embedder=embedder, vector_store=store)
    docs = [
        _doc(institution="jangseogak", external_id="A"),
        _doc(institution="nlk", external_id="B"),
        _doc(institution="nlk", external_id="C"),
    ]
    result = indexer.index_documents(docs)
    assert result.upserted == {"jangseogak": 1}
    assert result.errored == {"nlk": 2}


def test_index_documents_empty_input_returns_empty_result() -> None:
    indexer, _, _ = _indexer()
    result = indexer.index_documents([])
    assert result.upserted == {}
    assert result.errored == {}
    assert result.skipped_unknown_namespace == {}


def test_index_documents_writes_restricts_and_metadata() -> None:
    indexer, store, _ = _indexer()
    indexer.index_documents([_doc(period="조선후기", region="충청")])
    # The mock adapter exposes restricts via its internal storage; we
    # exercise that path through query+restricts which round-trips them.
    matches = store.query(
        "jangseogak",
        [1.0] * 32,
        top_k=5,
        restricts={"period": ["조선후기"]},
    )
    assert [m.datapoint_id for m in matches] == ["jangseogak:1"]
    assert matches[0].metadata["title"] == "음식디미방"
    assert matches[0].metadata["region"] == "충청"


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


def test_query_returns_matches_from_specified_namespace() -> None:
    indexer, _, _ = _indexer()
    indexer.index_documents(
        [
            _doc(institution="jangseogak", external_id="A"),
            _doc(institution="nlk", external_id="B"),
        ]
    )
    matches = indexer.query("jangseogak", "음식디미방", top_k=5)
    assert [m.datapoint_id for m in matches] == ["jangseogak:A"]


def test_query_unknown_namespace_raises() -> None:
    indexer, _, _ = _indexer(
        namespaces=["jangseogak"],
        allowed_namespaces=["jangseogak"],
    )
    with pytest.raises(VectorIndexNotConfiguredError, match="unknown namespace"):
        indexer.query("nlk", "x", top_k=3)


def test_query_passes_restricts_through() -> None:
    indexer, store, _ = _indexer()
    indexer.index_documents(
        [
            _doc(institution="jangseogak", external_id="A", period="조선후기"),
            _doc(institution="jangseogak", external_id="B", period="고려"),
        ]
    )
    matches = indexer.query("jangseogak", "x", top_k=5, restricts={"period": ["조선후기"]})
    assert [m.datapoint_id for m in matches] == ["jangseogak:A"]


# ---------------------------------------------------------------------------
# query_all_sources
# ---------------------------------------------------------------------------


def test_query_all_sources_fans_out_and_sorts_by_score() -> None:
    indexer, _, _ = _indexer()
    indexer.index_documents(
        [
            _doc(institution="jangseogak", external_id="A"),
            _doc(institution="koreanstudies", external_id="B"),
            _doc(institution="nlk", external_id="C"),
        ]
    )
    # The exact ordering depends on hash similarity, but every doc must
    # appear exactly once with its correct namespace.
    matches = indexer.query_all_sources("음식디미방", top_k=10)
    by_id = {m.match.datapoint_id: m for m in matches}
    assert set(by_id.keys()) == {
        "jangseogak:A",
        "koreanstudies:B",
        "nlk:C",
    }
    assert by_id["jangseogak:A"].namespace == "jangseogak"
    assert by_id["koreanstudies:B"].namespace == "koreanstudies"
    assert by_id["nlk:C"].namespace == "nlk"
    # Scores are weakly decreasing.
    scores = [m.match.score for m in matches]
    assert scores == sorted(scores, reverse=True)


def test_query_all_sources_isolates_failure_per_namespace() -> None:
    embedder = MockEmbeddingAdapter(dimension=8)
    store = MagicMock()
    store.known_namespaces.return_value = ["jangseogak", "nlk"]

    def fake_query(namespace, vector, *, top_k, restricts=None):
        if namespace == "jangseogak":
            return [VectorMatch(datapoint_id="jangseogak:A", score=0.9)]
        raise RuntimeError("nlk endpoint down")

    store.query.side_effect = fake_query
    indexer = HeritageIndexer(embedder=embedder, vector_store=store)
    matches = indexer.query_all_sources("음식디미방", top_k=10)
    # Only the surviving namespace contributes — failure isolated.
    assert [(m.namespace, m.match.datapoint_id) for m in matches] == [
        ("jangseogak", "jangseogak:A")
    ]


def test_query_all_sources_re_raises_namespace_misconfigured() -> None:
    # ``allowed_namespaces`` is wider than what the store knows.
    embedder = MockEmbeddingAdapter(dimension=8)
    store = MockVectorSearchAdapter(namespaces=["jangseogak"])
    indexer = HeritageIndexer(
        embedder=embedder,
        vector_store=store,
        allowed_namespaces=["jangseogak", "nlk"],
    )
    with pytest.raises(VectorIndexNotConfiguredError):
        indexer.query_all_sources("x", top_k=3)


def test_query_all_sources_top_k_trims_merged_results() -> None:
    indexer, _, _ = _indexer()
    indexer.index_documents(
        [_doc(institution="jangseogak", external_id=f"A{i}", title=f"T{i}") for i in range(5)]
        + [_doc(institution="koreanstudies", external_id=f"B{i}", title=f"T{i}") for i in range(5)]
    )
    matches = indexer.query_all_sources("음식디미방", top_k=3)
    assert len(matches) == 3
    # Each match annotated with its namespace.
    assert all(isinstance(m, CrossSourceMatch) for m in matches)
