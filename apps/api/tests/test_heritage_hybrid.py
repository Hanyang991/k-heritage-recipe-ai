"""Tests for :class:`HybridHeritageAdapter` — keyword + semantic blend."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.embeddings.mock import MockEmbeddingAdapter
from app.services.heritage.base import DocumentMatch, HeritageDoc
from app.services.heritage.hybrid import HybridHeritageAdapter
from app.services.heritage.mock import MockHeritageAdapter
from app.services.vector_search.base import VectorIndexNotConfiguredError
from app.services.vector_search.indexer import (
    HeritageIndexer,
    heritage_doc_metadata,
    vector_match_to_heritage_doc,
)
from app.services.vector_search.mock import MockVectorSearchAdapter


def _doc(
    *,
    external_id: str = "1",
    title: str = "음식디미방",
    institution: str = "jangseogak",
    region: str = "경상도",
    period: str = "조선후기",
    year: int = 1670,
    category: str = "조리서",
    original_text: str = "쑥의 어린 잎을 데쳐 다져 꿀과 잣가루를 더한다.",
    summary: str = "한국 최초의 한글 조리서.",
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


def _build_hybrid(
    *,
    keyword_adapter=None,
    namespaces=("jangseogak", "koreanstudies", "nlk", "gihohak"),
    seeded_docs: list[HeritageDoc] | None = None,
    keyword_weight: float = 0.6,
    semantic_top_k: int = 10,
) -> tuple[HybridHeritageAdapter, MockVectorSearchAdapter]:
    """Build a hybrid adapter wired to mock keyword + mock vector store."""
    embedder = MockEmbeddingAdapter(dimension=32)
    vector_store = MockVectorSearchAdapter(namespaces=list(namespaces))
    indexer = HeritageIndexer(embedder=embedder, vector_store=vector_store)
    if seeded_docs:
        indexer.index_documents(seeded_docs)
    hybrid = HybridHeritageAdapter(
        keyword_adapter=keyword_adapter or MockHeritageAdapter(),
        indexer=indexer,
        keyword_weight=keyword_weight,
        semantic_top_k=semantic_top_k,
    )
    return hybrid, vector_store


# ---------------------------------------------------------------------------
# Metadata round-trip
# ---------------------------------------------------------------------------


class _Match:
    """Tiny shim with the :class:`VectorMatch` attribute surface."""

    def __init__(
        self,
        datapoint_id: str,
        score: float,
        metadata: dict[str, str],
    ) -> None:
        self.datapoint_id = datapoint_id
        self.score = score
        self.metadata = metadata


def test_metadata_includes_summary_and_category() -> None:
    doc = _doc(summary="고문헌 요약", category="조리서")
    md = heritage_doc_metadata(doc)
    assert md["summary"] == "고문헌 요약"
    assert md["category"] == "조리서"


def test_metadata_omits_empty_summary_and_category() -> None:
    doc = _doc(summary="", category="")
    md = heritage_doc_metadata(doc)
    assert "summary" not in md
    assert "category" not in md


def test_vector_match_to_heritage_doc_round_trips() -> None:
    original = _doc()
    md = heritage_doc_metadata(original)
    match = _Match(
        datapoint_id=f"{original.institution}:{original.external_id}",
        score=0.91,
        metadata=md,
    )
    reconstructed = vector_match_to_heritage_doc(original.institution, match)
    assert reconstructed.external_id == original.external_id
    assert reconstructed.institution == original.institution
    assert reconstructed.title == original.title
    assert reconstructed.region == original.region
    assert reconstructed.period == original.period
    assert reconstructed.category == original.category
    assert reconstructed.year == original.year
    assert reconstructed.summary == original.summary
    assert reconstructed.license == original.license
    # original_text is intentionally dropped from the metadata blob.
    assert reconstructed.original_text == ""


def test_vector_match_to_heritage_doc_preserves_colon_in_external_id() -> None:
    # Archive shelf marks can contain colons — must round-trip intact.
    match = _Match(
        datapoint_id="jangseogak:K2-3456:vol01",
        score=0.5,
        metadata={
            "title": "test",
            "institution": "jangseogak",
            "license": "KOGL-1",
        },
    )
    doc = vector_match_to_heritage_doc("jangseogak", match)
    assert doc.external_id == "K2-3456:vol01"


def test_vector_match_to_heritage_doc_falls_back_to_namespace_for_missing_institution() -> None:
    match = _Match(
        datapoint_id="nlk:abc",
        score=0.5,
        metadata={"title": "t", "license": "KOGL-1"},
    )
    doc = vector_match_to_heritage_doc("nlk", match)
    assert doc.institution == "nlk"


def test_vector_match_to_heritage_doc_handles_invalid_year() -> None:
    # Vertex may return a stringified year that can't be parsed; treat as None.
    match = _Match(
        datapoint_id="nlk:abc",
        score=0.5,
        metadata={"year": "미상"},
    )
    doc = vector_match_to_heritage_doc("nlk", match)
    assert doc.year is None


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_hybrid_rejects_keyword_weight_out_of_range() -> None:
    indexer = HeritageIndexer(
        embedder=MockEmbeddingAdapter(dimension=8),
        vector_store=MockVectorSearchAdapter(namespaces=["jangseogak"]),
    )
    with pytest.raises(ValueError, match=r"keyword_weight must be in \[0, 1\]"):
        HybridHeritageAdapter(
            keyword_adapter=MockHeritageAdapter(),
            indexer=indexer,
            keyword_weight=1.5,
        )
    with pytest.raises(ValueError, match=r"keyword_weight must be in \[0, 1\]"):
        HybridHeritageAdapter(
            keyword_adapter=MockHeritageAdapter(),
            indexer=indexer,
            keyword_weight=-0.1,
        )


def test_hybrid_rejects_non_positive_semantic_top_k() -> None:
    indexer = HeritageIndexer(
        embedder=MockEmbeddingAdapter(dimension=8),
        vector_store=MockVectorSearchAdapter(namespaces=["jangseogak"]),
    )
    with pytest.raises(ValueError, match="semantic_top_k must be positive"):
        HybridHeritageAdapter(
            keyword_adapter=MockHeritageAdapter(),
            indexer=indexer,
            semantic_top_k=0,
        )


def test_hybrid_exposes_weight_properties() -> None:
    hybrid, _ = _build_hybrid(keyword_weight=0.75)
    assert hybrid.keyword_weight == 0.75
    assert hybrid.semantic_weight == 0.25


# ---------------------------------------------------------------------------
# Search — happy path
# ---------------------------------------------------------------------------


def test_search_returns_keyword_only_when_index_is_empty() -> None:
    """Empty index → semantic side contributes nothing; keyword passes through."""
    hybrid, _ = _build_hybrid(keyword_weight=1.0, seeded_docs=[])
    matches = hybrid.search("음식디미방", limit=3)
    titles = [m.document.title for m in matches]
    assert "음식디미방" in titles  # The mock keyword adapter returns it.


def test_search_combines_keyword_and_semantic_score_for_doc_in_both() -> None:
    """When a doc is matched by both layers, the score should be the weighted sum."""
    # Use a custom keyword adapter that returns one doc with score=0.8.
    doc = _doc(external_id="A", title="음식디미방", institution="jangseogak")
    keyword = MagicMock()
    keyword.search.return_value = [DocumentMatch(document=doc, match_score=0.8)]

    hybrid, _ = _build_hybrid(
        keyword_adapter=keyword,
        seeded_docs=[doc],  # Same doc lives in the index too.
        keyword_weight=0.7,
        semantic_top_k=5,
    )
    matches = hybrid.search("음식디미방", limit=5)
    by_id = {m.document.external_id: m for m in matches}
    assert "A" in by_id
    # Expected: 0.7 * 0.8 + 0.3 * sim_score (sim_score = 1.0 for same vector).
    # Mock embedder hashes the same query string → score is high but not
    # guaranteed exactly 1.0 (the indexed text differs from the bare query).
    # We just assert the score is > 0.7 * 0.8 (keyword-only floor).
    assert by_id["A"].match_score >= 0.7 * 0.8
    # Single-side keyword would be 0.7 * 0.8 = 0.56; combined should exceed.
    assert by_id["A"].match_score > 0.7 * 0.8


def test_search_surfaces_semantic_only_doc_not_in_keyword_results() -> None:
    """The key value-add: a doc that only the semantic side finds."""
    # Keyword adapter returns 0 matches.
    keyword = MagicMock()
    keyword.search.return_value = []

    semantic_doc = _doc(external_id="SEM", title="궁중 음식", institution="jangseogak")
    hybrid, _ = _build_hybrid(
        keyword_adapter=keyword,
        seeded_docs=[semantic_doc],
        keyword_weight=0.5,
    )
    matches = hybrid.search("food", limit=5)
    # Even though keyword found nothing, the semantic side surfaced
    # the indexed doc with non-zero similarity.
    ext_ids = [m.document.external_id for m in matches]
    assert "SEM" in ext_ids


def test_search_passes_region_and_period_to_semantic_restricts() -> None:
    """Region / period filters must propagate to Vertex AI restricts."""
    indexer = MagicMock()
    indexer.allowed_namespaces = ["jangseogak"]
    indexer.query_all_sources.return_value = []
    hybrid = HybridHeritageAdapter(
        keyword_adapter=MockHeritageAdapter(),
        indexer=indexer,
        keyword_weight=0.5,
    )
    hybrid.search("쑥", region="경상도", period="조선후기", limit=3)
    call_kwargs = indexer.query_all_sources.call_args.kwargs
    assert call_kwargs["restricts"] == {
        "region": ["경상도"],
        "period": ["조선후기"],
    }


def test_search_omits_restricts_when_no_filters() -> None:
    """Empty filters → restricts=None, not an empty dict."""
    indexer = MagicMock()
    indexer.allowed_namespaces = ["jangseogak"]
    indexer.query_all_sources.return_value = []
    hybrid = HybridHeritageAdapter(
        keyword_adapter=MockHeritageAdapter(),
        indexer=indexer,
        keyword_weight=0.5,
    )
    hybrid.search("쑥", limit=3)
    call_kwargs = indexer.query_all_sources.call_args.kwargs
    assert call_kwargs["restricts"] is None


def test_search_respects_limit_after_merge() -> None:
    """Each layer can return more, but the final list is trimmed to limit."""
    docs = [_doc(external_id=f"D{i}", title=f"문헌{i}") for i in range(8)]
    keyword = MagicMock()
    keyword.search.return_value = [DocumentMatch(document=d, match_score=0.5) for d in docs]
    hybrid, _ = _build_hybrid(
        keyword_adapter=keyword,
        seeded_docs=docs,
        keyword_weight=0.6,
        semantic_top_k=10,
    )
    matches = hybrid.search("문헌", limit=3)
    assert len(matches) == 3


def test_search_results_sorted_by_combined_score_desc() -> None:
    """Top-scoring doc must come first after the merge sort."""
    high = _doc(external_id="HIGH", title="HIGH")
    low = _doc(external_id="LOW", title="LOW")
    keyword = MagicMock()
    keyword.search.return_value = [
        DocumentMatch(document=high, match_score=0.9),
        DocumentMatch(document=low, match_score=0.1),
    ]
    hybrid, _ = _build_hybrid(
        keyword_adapter=keyword,
        keyword_weight=1.0,  # Pure keyword for deterministic comparison.
    )
    matches = hybrid.search("x", limit=5)
    assert [m.document.external_id for m in matches] == ["HIGH", "LOW"]
    assert matches[0].match_score > matches[1].match_score


# ---------------------------------------------------------------------------
# Search — resilience
# ---------------------------------------------------------------------------


def test_search_isolates_keyword_failure() -> None:
    """Keyword raises → semantic side still contributes."""
    keyword = MagicMock()
    keyword.search.side_effect = RuntimeError("upstream timeout")
    doc = _doc(external_id="SEM", title="궁중 음식", institution="jangseogak")
    hybrid, _ = _build_hybrid(
        keyword_adapter=keyword,
        seeded_docs=[doc],
        keyword_weight=0.5,
    )
    matches = hybrid.search("음식", limit=3)
    # Semantic side still found the indexed doc; no exception bubbled up.
    ext_ids = [m.document.external_id for m in matches]
    assert "SEM" in ext_ids


def test_search_isolates_semantic_failure() -> None:
    """Semantic raises → keyword side still contributes."""
    doc = _doc(external_id="KW", title="음식디미방", institution="jangseogak")
    keyword = MagicMock()
    keyword.search.return_value = [DocumentMatch(document=doc, match_score=0.9)]

    indexer = MagicMock()
    indexer.allowed_namespaces = ["jangseogak"]
    indexer.query_all_sources.side_effect = RuntimeError("vertex down")
    hybrid = HybridHeritageAdapter(
        keyword_adapter=keyword,
        indexer=indexer,
        keyword_weight=0.6,
    )
    matches = hybrid.search("음식디미방", limit=3)
    assert [m.document.external_id for m in matches] == ["KW"]


def test_search_falls_back_when_both_layers_fail() -> None:
    """Both layers raise → final fallback re-calls the keyword adapter."""
    keyword = MagicMock()
    # First two calls raise (during initial try-block), third (fallback) returns.
    keyword.search.side_effect = [
        RuntimeError("first"),
        [DocumentMatch(document=_doc(), match_score=0.5)],
    ]
    indexer = MagicMock()
    indexer.allowed_namespaces = ["jangseogak"]
    indexer.query_all_sources.side_effect = RuntimeError("vertex down")
    hybrid = HybridHeritageAdapter(
        keyword_adapter=keyword,
        indexer=indexer,
        keyword_weight=0.6,
    )
    matches = hybrid.search("음식디미방", limit=3)
    assert len(matches) == 1
    assert keyword.search.call_count == 2


def test_search_propagates_namespace_misconfigured_loudly() -> None:
    """VectorIndexNotConfiguredError is a config bug — must NOT be silenced."""
    indexer = MagicMock()
    indexer.allowed_namespaces = ["jangseogak"]
    indexer.query_all_sources.side_effect = VectorIndexNotConfiguredError("namespace mismatch")
    hybrid = HybridHeritageAdapter(
        keyword_adapter=MockHeritageAdapter(),
        indexer=indexer,
        keyword_weight=0.5,
    )
    with pytest.raises(VectorIndexNotConfiguredError):
        hybrid.search("x", limit=3)


def test_search_returns_empty_when_both_layers_return_empty() -> None:
    """Both layers answered with no hits → [] honestly, no mock fallback."""
    keyword = MagicMock()
    keyword.search.return_value = []
    hybrid, _ = _build_hybrid(
        keyword_adapter=keyword,
        seeded_docs=[],  # Empty index.
        keyword_weight=0.5,
    )
    assert hybrid.search("얼토당토않은단어", limit=3) == []


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------


def test_dedupe_by_identity_key_combines_scores() -> None:
    """Same (institution, external_id) from both layers → combined score, one entry."""
    doc = _doc(external_id="DUP", title="중복문헌", institution="jangseogak")
    keyword = MagicMock()
    keyword.search.return_value = [DocumentMatch(document=doc, match_score=0.5)]

    hybrid, _ = _build_hybrid(
        keyword_adapter=keyword,
        seeded_docs=[doc],
        keyword_weight=0.5,
    )
    matches = hybrid.search("중복문헌", limit=5)
    ext_ids = [m.document.external_id for m in matches]
    assert ext_ids.count("DUP") == 1


def test_dedupe_prefers_keyword_doc_payload() -> None:
    """Keyword's HeritageDoc carries original_text; semantic's doesn't.

    For same (institution, external_id), the keyword doc must win the
    dataclass slot so downstream callers still see the richer payload.
    """
    doc_kw = _doc(
        external_id="DUP",
        title="중복문헌",
        institution="jangseogak",
        original_text="원문 내용이 있는 키워드 doc",
    )
    keyword = MagicMock()
    keyword.search.return_value = [DocumentMatch(document=doc_kw, match_score=0.5)]

    # Index has the same doc, but vector_match_to_heritage_doc leaves
    # original_text="" by design.
    hybrid, _ = _build_hybrid(
        keyword_adapter=keyword,
        seeded_docs=[doc_kw],
        keyword_weight=0.5,
    )
    matches = hybrid.search("중복문헌", limit=5)
    dup = next(m for m in matches if m.document.external_id == "DUP")
    assert dup.document.original_text == "원문 내용이 있는 키워드 doc"


def test_dedupe_by_normalised_title_collapses_cross_source_duplicates() -> None:
    """Same title from different institutions → one entry, higher score wins."""
    doc_jsg = _doc(
        external_id="A",
        title="음식 디미방",  # With whitespace — should normalise to same key.
        institution="jangseogak",
    )
    doc_nlk = _doc(
        external_id="B",
        title="음식디미방",
        institution="nlk",
    )
    keyword = MagicMock()
    keyword.search.return_value = [
        DocumentMatch(document=doc_jsg, match_score=0.4),
        DocumentMatch(document=doc_nlk, match_score=0.9),
    ]
    hybrid, _ = _build_hybrid(
        keyword_adapter=keyword,
        namespaces=("jangseogak", "nlk"),
        seeded_docs=[],
        keyword_weight=1.0,
    )
    matches = hybrid.search("음식디미방", limit=5)
    assert len(matches) == 1
    # Higher score wins — that's the NLK record.
    assert matches[0].document.institution == "nlk"


# ---------------------------------------------------------------------------
# list_seeded delegates to keyword
# ---------------------------------------------------------------------------


def test_list_seeded_delegates_to_keyword_adapter() -> None:
    keyword = MagicMock()
    sentinel = [_doc(external_id="seed1", title="seed1")]
    keyword.list_seeded.return_value = sentinel
    indexer = HeritageIndexer(
        embedder=MockEmbeddingAdapter(dimension=8),
        vector_store=MockVectorSearchAdapter(namespaces=["jangseogak"]),
    )
    hybrid = HybridHeritageAdapter(
        keyword_adapter=keyword,
        indexer=indexer,
        keyword_weight=0.5,
    )
    assert hybrid.list_seeded() is sentinel


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------


def test_factory_returns_plain_adapter_in_keyword_mode(monkeypatch) -> None:
    """Default mode = keyword — no HybridHeritageAdapter wrapper."""
    from app.config import get_settings
    from app.services.heritage import get_heritage_adapter

    get_settings.cache_clear()
    get_heritage_adapter.cache_clear()
    monkeypatch.setenv("HERITAGE_RETRIEVAL_MODE", "keyword")
    try:
        adapter = get_heritage_adapter()
    finally:
        get_settings.cache_clear()
        get_heritage_adapter.cache_clear()
    assert not isinstance(adapter, HybridHeritageAdapter)


def test_factory_returns_hybrid_adapter_in_hybrid_mode(monkeypatch) -> None:
    from app.config import get_settings
    from app.services.embeddings import get_embedding_adapter
    from app.services.heritage import get_heritage_adapter
    from app.services.vector_search import get_vector_search_adapter

    get_settings.cache_clear()
    get_heritage_adapter.cache_clear()
    get_embedding_adapter.cache_clear()
    get_vector_search_adapter.cache_clear()
    monkeypatch.setenv("HERITAGE_RETRIEVAL_MODE", "hybrid")
    try:
        adapter = get_heritage_adapter()
    finally:
        get_settings.cache_clear()
        get_heritage_adapter.cache_clear()
        get_embedding_adapter.cache_clear()
        get_vector_search_adapter.cache_clear()
    assert isinstance(adapter, HybridHeritageAdapter)


def test_factory_honours_weight_override(monkeypatch) -> None:
    from app.config import get_settings
    from app.services.embeddings import get_embedding_adapter
    from app.services.heritage import get_heritage_adapter
    from app.services.vector_search import get_vector_search_adapter

    get_settings.cache_clear()
    get_heritage_adapter.cache_clear()
    get_embedding_adapter.cache_clear()
    get_vector_search_adapter.cache_clear()
    monkeypatch.setenv("HERITAGE_RETRIEVAL_MODE", "hybrid")
    monkeypatch.setenv("HERITAGE_HYBRID_KEYWORD_WEIGHT", "0.3")
    try:
        adapter = get_heritage_adapter()
    finally:
        get_settings.cache_clear()
        get_heritage_adapter.cache_clear()
        get_embedding_adapter.cache_clear()
        get_vector_search_adapter.cache_clear()
    assert isinstance(adapter, HybridHeritageAdapter)
    assert adapter.keyword_weight == 0.3
    assert adapter.semantic_weight == pytest.approx(0.7)
