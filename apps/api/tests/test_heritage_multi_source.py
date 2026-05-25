"""Tests for :class:`MultiSourceHeritageAdapter` and the ``multi`` factory branch."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.heritage import (
    HeritageSource,
    LiveGihohakAdapter,
    LiveHeritageAdapter,
    LiveKoreanstudiesAdapter,
    LiveNlkAdapter,
    MockHeritageAdapter,
    MultiSourceHeritageAdapter,
    get_heritage_adapter,
)
from app.services.heritage.base import DocumentMatch, HeritageDoc
from app.services.heritage.multi_source import _normalise_title_for_dedupe


def _doc(
    *,
    external_id: str,
    title: str,
    institution: str = "jangseogak",
    region: str = "",
    period: str = "조선후기",
    year: int = 1700,
) -> HeritageDoc:
    return HeritageDoc(
        external_id=external_id,
        title=title,
        institution=institution,
        region=region,
        period=period,
        category="고문헌",
        year=year,
        original_text="",
        summary="",
    )


def _match(
    *,
    external_id: str,
    title: str,
    score: float,
    institution: str = "jangseogak",
) -> DocumentMatch:
    return DocumentMatch(
        document=_doc(external_id=external_id, title=title, institution=institution),
        match_score=score,
    )


def _adapter(matches: list[DocumentMatch]) -> MagicMock:
    a = MagicMock()
    a.search.return_value = matches
    return a


# ---------------------------------------------------------------------------
# Title normalisation helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("음식디미방", "음식디미방"),
        ("음식 디미방", "음식디미방"),  # whitespace stripped
        ("飮食知味方", "飮食知味方"),  # CJK preserved
        ("Recipe (1670)", "recipe1670"),  # punctuation stripped, lowercased
        ("", ""),
        ("   ", ""),  # all whitespace
        ("!!!", ""),  # all punctuation
    ],
)
def test_normalise_title_for_dedupe(title: str, expected: str) -> None:
    assert _normalise_title_for_dedupe(title) == expected


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_multi_source_requires_at_least_one_source() -> None:
    with pytest.raises(ValueError, match="at least one source"):
        MultiSourceHeritageAdapter(sources=[])


def test_multi_source_constructs_with_single_source() -> None:
    adapter = MultiSourceHeritageAdapter(sources=[HeritageSource("jangseogak", _adapter([]))])
    assert len(adapter.sources) == 1
    assert adapter.sources[0].name == "jangseogak"


def test_multi_source_sources_property_returns_copy() -> None:
    src = HeritageSource("jangseogak", _adapter([]))
    adapter = MultiSourceHeritageAdapter(sources=[src])
    snapshot = adapter.sources
    snapshot.append(HeritageSource("other", _adapter([])))
    # Internal list unchanged — `sources` returned a copy.
    assert len(adapter.sources) == 1


# ---------------------------------------------------------------------------
# search() — happy path / fan-in
# ---------------------------------------------------------------------------


def test_multi_source_search_merges_results_from_all_sources() -> None:
    a1 = _adapter([_match(external_id="JS-1", title="음식디미방", score=0.94)])
    a2 = _adapter(
        [_match(external_id="KS-1", title="요록", score=0.80, institution="koreanstudies")]
    )
    a3 = _adapter(
        [_match(external_id="GH-1", title="향약구급방", score=0.70, institution="gihohak")]
    )

    adapter = MultiSourceHeritageAdapter(
        sources=[
            HeritageSource("jangseogak", a1),
            HeritageSource("koreanstudies", a2),
            HeritageSource("gihohak", a3),
        ]
    )
    results = adapter.search("음식")
    assert {m.document.external_id for m in results} == {"JS-1", "KS-1", "GH-1"}
    assert [m.match_score for m in results] == [0.94, 0.80, 0.70]  # sorted descending


def test_multi_source_search_forwards_all_filters_to_each_source() -> None:
    a1 = _adapter([])
    a2 = _adapter([])
    adapter = MultiSourceHeritageAdapter(
        sources=[
            HeritageSource("jangseogak", a1),
            HeritageSource("gihohak", a2),
        ]
    )
    adapter.search("음식", region="충청", period="조선후기", limit=5)

    for a in (a1, a2):
        a.search.assert_called_once_with("음식", region="충청", period="조선후기", limit=5)


def test_multi_source_search_trims_to_limit_after_merging() -> None:
    a1 = _adapter(
        [_match(external_id=f"JS-{i}", title=f"doc{i}", score=0.9 - 0.1 * i) for i in range(5)]
    )
    a2 = _adapter(
        [
            _match(
                external_id=f"GH-{i}", title=f"gh{i}", score=0.85 - 0.1 * i, institution="gihohak"
            )
            for i in range(5)
        ]
    )

    adapter = MultiSourceHeritageAdapter(
        sources=[
            HeritageSource("jangseogak", a1),
            HeritageSource("gihohak", a2),
        ]
    )
    results = adapter.search("음식", limit=3)
    assert len(results) == 3
    assert [m.match_score for m in results] == sorted(
        [m.match_score for m in results], reverse=True
    )


def test_multi_source_search_ties_broken_by_title_for_stable_order() -> None:
    a1 = _adapter([_match(external_id="JS-1", title="zeta", score=0.5)])
    a2 = _adapter(
        [_match(external_id="KS-1", title="alpha", score=0.5, institution="koreanstudies")]
    )

    adapter = MultiSourceHeritageAdapter(
        sources=[
            HeritageSource("jangseogak", a1),
            HeritageSource("koreanstudies", a2),
        ]
    )
    results = adapter.search("음식")
    assert [m.document.title for m in results] == ["alpha", "zeta"]


# ---------------------------------------------------------------------------
# search() — dedupe behaviour
# ---------------------------------------------------------------------------


def test_multi_source_search_dedupes_intra_source_by_external_id() -> None:
    """A single source returning two rows with the same id keeps only the higher-scored one."""
    a1 = _adapter(
        [
            _match(external_id="JS-1", title="음식디미방", score=0.5),
            _match(external_id="JS-1", title="음식디미방", score=0.94),
        ]
    )
    adapter = MultiSourceHeritageAdapter(sources=[HeritageSource("jangseogak", a1)])
    results = adapter.search("음식")
    assert len(results) == 1
    assert results[0].match_score == 0.94


def test_multi_source_search_dedupes_cross_source_by_title() -> None:
    """The same record surfacing from two archives collapses to the higher-scored copy."""
    a1 = _adapter(
        [
            _match(external_id="JS-1", title="음식디미방", score=0.94),
        ]
    )
    a2 = _adapter(
        [
            # Same title (with whitespace variation), surfaced from koreanstudies.
            _match(
                external_id="KS-7",
                title="음식 디미방",  # spaced
                score=0.80,
                institution="koreanstudies",
            ),
        ]
    )

    adapter = MultiSourceHeritageAdapter(
        sources=[
            HeritageSource("jangseogak", a1),
            HeritageSource("koreanstudies", a2),
        ]
    )
    results = adapter.search("음식")
    # Title-based dedupe keeps the higher-scored 장서각 copy.
    assert len(results) == 1
    assert results[0].document.external_id == "JS-1"
    assert results[0].match_score == 0.94


def test_multi_source_search_keeps_different_records_with_different_titles() -> None:
    a1 = _adapter([_match(external_id="JS-1", title="음식디미방", score=0.94)])
    a2 = _adapter(
        [_match(external_id="KS-1", title="규합총서", score=0.80, institution="koreanstudies")]
    )

    adapter = MultiSourceHeritageAdapter(
        sources=[
            HeritageSource("jangseogak", a1),
            HeritageSource("koreanstudies", a2),
        ]
    )
    results = adapter.search("음식")
    assert len(results) == 2


def test_multi_source_search_does_not_dedupe_records_with_empty_titles() -> None:
    """Rows that have empty (post-normalisation) titles are kept separate.

    Without this carve-out a single all-punctuation title across two
    sources would collapse to one row — but those are usually genuinely
    distinct records that just need stable cross-archive ordering by id.
    """
    a1 = _adapter([_match(external_id="JS-1", title="!!!", score=0.94)])
    a2 = _adapter(
        [_match(external_id="KS-1", title="!!!", score=0.80, institution="koreanstudies")]
    )

    adapter = MultiSourceHeritageAdapter(
        sources=[
            HeritageSource("jangseogak", a1),
            HeritageSource("koreanstudies", a2),
        ]
    )
    results = adapter.search("음식")
    assert {m.document.external_id for m in results} == {"JS-1", "KS-1"}


# ---------------------------------------------------------------------------
# search() — failure isolation
# ---------------------------------------------------------------------------


def test_multi_source_search_isolates_single_source_failure() -> None:
    failing = MagicMock()
    failing.search.side_effect = RuntimeError("upstream timeout")

    healthy = _adapter(
        [_match(external_id="KS-1", title="요록", score=0.80, institution="koreanstudies")]
    )

    adapter = MultiSourceHeritageAdapter(
        sources=[
            HeritageSource("jangseogak", failing),
            HeritageSource("koreanstudies", healthy),
        ]
    )
    results = adapter.search("음식")
    # Healthy source still contributes; failing one silently dropped.
    assert len(results) == 1
    assert results[0].document.external_id == "KS-1"


def test_multi_source_search_falls_back_to_mock_when_all_sources_fail() -> None:
    f1 = MagicMock()
    f1.search.side_effect = RuntimeError("nope")
    f2 = MagicMock()
    f2.search.side_effect = ConnectionError("nope")

    fallback = MagicMock()
    fallback.search.return_value = [
        DocumentMatch(
            document=_doc(external_id="mock-1", title="seeded", institution="mock"),
            match_score=0.9,
        )
    ]

    adapter = MultiSourceHeritageAdapter(
        sources=[
            HeritageSource("jangseogak", f1),
            HeritageSource("koreanstudies", f2),
        ],
        fallback=fallback,
    )
    results = adapter.search("음식", region="충청", period="조선후기", limit=5)
    fallback.search.assert_called_once_with("음식", region="충청", period="조선후기", limit=5)
    assert results[0].document.external_id == "mock-1"


def test_multi_source_search_empty_results_do_not_trigger_fallback() -> None:
    """If every source answers cleanly but with zero hits, return [] — empty is real info."""
    a1 = _adapter([])
    a2 = _adapter([])
    fallback = MagicMock()
    fallback.search.return_value = [MagicMock()]

    adapter = MultiSourceHeritageAdapter(
        sources=[
            HeritageSource("jangseogak", a1),
            HeritageSource("koreanstudies", a2),
        ],
        fallback=fallback,
    )
    results = adapter.search("nothing-matches")
    assert results == []
    fallback.search.assert_not_called()


def test_multi_source_search_partial_failure_does_not_trigger_fallback() -> None:
    """Even when N-1 sources fail, the surviving 1 prevents the all-sources-fail escalation."""
    failing = MagicMock()
    failing.search.side_effect = RuntimeError("nope")

    healthy = _adapter([_match(external_id="KS-1", title="요록", score=0.8)])
    fallback = MagicMock()

    adapter = MultiSourceHeritageAdapter(
        sources=[
            HeritageSource("jangseogak", failing),
            HeritageSource("koreanstudies", healthy),
        ],
        fallback=fallback,
    )
    results = adapter.search("음식")
    fallback.search.assert_not_called()
    assert len(results) == 1


# ---------------------------------------------------------------------------
# list_seeded()
# ---------------------------------------------------------------------------


def test_multi_source_list_seeded_delegates_to_fallback() -> None:
    adapter = MultiSourceHeritageAdapter(sources=[HeritageSource("jangseogak", _adapter([]))])
    seeded = adapter.list_seeded()
    # Mock fallback ships 3 seed documents.
    assert len(seeded) == 3


# ---------------------------------------------------------------------------
# Factory routing
# ---------------------------------------------------------------------------


def _reset_caches() -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    get_heritage_adapter.cache_clear()


def test_factory_returns_multi_when_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "multi")
    monkeypatch.delenv("HERITAGE_MULTI_SOURCES", raising=False)
    _reset_caches()
    adapter = get_heritage_adapter()
    assert isinstance(adapter, MultiSourceHeritageAdapter)
    # Default sources list excludes nlk (requires a key) — 3 entries.
    assert [s.name for s in adapter.sources] == [
        "jangseogak",
        "koreanstudies",
        "gihohak",
    ]


def test_factory_multi_includes_nlk_when_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "multi")
    monkeypatch.setenv("HERITAGE_MULTI_SOURCES", "jangseogak,koreanstudies,nlk,gihohak")
    monkeypatch.setenv("NLK_API_KEY", "test-key")
    _reset_caches()
    adapter = get_heritage_adapter()
    assert isinstance(adapter, MultiSourceHeritageAdapter)
    assert [s.name for s in adapter.sources] == [
        "jangseogak",
        "koreanstudies",
        "nlk",
        "gihohak",
    ]


def test_factory_multi_skips_nlk_when_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "multi")
    monkeypatch.setenv("HERITAGE_MULTI_SOURCES", "jangseogak,nlk,gihohak")
    monkeypatch.delenv("NLK_API_KEY", raising=False)
    _reset_caches()
    adapter = get_heritage_adapter()
    assert isinstance(adapter, MultiSourceHeritageAdapter)
    # NLK silently dropped — surviving 2 sources still build a valid multi-adapter.
    assert [s.name for s in adapter.sources] == ["jangseogak", "gihohak"]


def test_factory_multi_falls_back_to_mock_when_no_valid_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "multi")
    monkeypatch.setenv("HERITAGE_MULTI_SOURCES", "nonsense,also-nonsense")
    _reset_caches()
    adapter = get_heritage_adapter()
    assert isinstance(adapter, MockHeritageAdapter)


def test_factory_multi_skips_unknown_source_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "multi")
    monkeypatch.setenv("HERITAGE_MULTI_SOURCES", "jangseogak,nonsense,gihohak")
    _reset_caches()
    adapter = get_heritage_adapter()
    assert isinstance(adapter, MultiSourceHeritageAdapter)
    assert [s.name for s in adapter.sources] == ["jangseogak", "gihohak"]


def test_factory_multi_strips_whitespace_in_source_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "multi")
    monkeypatch.setenv("HERITAGE_MULTI_SOURCES", " jangseogak , koreanstudies , gihohak ")
    _reset_caches()
    adapter = get_heritage_adapter()
    assert isinstance(adapter, MultiSourceHeritageAdapter)
    assert [s.name for s in adapter.sources] == [
        "jangseogak",
        "koreanstudies",
        "gihohak",
    ]


def test_factory_multi_each_source_uses_correct_adapter_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "multi")
    monkeypatch.setenv("HERITAGE_MULTI_SOURCES", "jangseogak,koreanstudies,nlk,gihohak")
    monkeypatch.setenv("NLK_API_KEY", "test-key")
    _reset_caches()
    adapter = get_heritage_adapter()
    assert isinstance(adapter, MultiSourceHeritageAdapter)
    by_name = {s.name: s.adapter for s in adapter.sources}
    assert isinstance(by_name["jangseogak"], LiveHeritageAdapter)
    assert isinstance(by_name["koreanstudies"], LiveKoreanstudiesAdapter)
    assert isinstance(by_name["nlk"], LiveNlkAdapter)
    assert isinstance(by_name["gihohak"], LiveGihohakAdapter)


def test_factory_multi_settings_property_parses_comma_list() -> None:
    from app.config import Settings

    s = Settings(heritage_multi_sources="jangseogak, koreanstudies, gihohak")
    assert s.heritage_multi_sources_list == ["jangseogak", "koreanstudies", "gihohak"]


def test_factory_multi_settings_property_handles_empty_list() -> None:
    from app.config import Settings

    s = Settings(heritage_multi_sources="")
    assert s.heritage_multi_sources_list == []
