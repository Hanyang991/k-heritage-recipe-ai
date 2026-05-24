"""Tests for :class:`LiveKoreanstudiesAdapter` and factory routing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.heritage import (
    LiveHeritageAdapter,
    LiveKoreanstudiesAdapter,
    MockHeritageAdapter,
    get_heritage_adapter,
)
from app.services.heritage.base import DocumentMatch, HeritageDoc
from app.services.heritage.koreanstudies import (
    KoreanstudiesAPIError,
    KoreanstudiesSearchResponse,
    KoreanstudiesSearchResult,
)


def _result(
    idx: int,
    *,
    year: int | None = 1874,
    period: str = "조선후기",
    region_modern: str = "서울특별시",
    region_historical: str = "한성",
) -> KoreanstudiesSearchResult:
    return KoreanstudiesSearchResult(
        external_id=f"UCI_DEMO{idx:03d}",
        title=f"테스트 자료 {idx}",
        detail_url=f"http://kostma.aks.ac.kr/inspection/insDirView.aspx?dataUCI=UCI_DEMO{idx:03d}",
        type_category="고문서-치부기록류-발기",
        content_category="국왕/왕실-의례-발기",
        region_modern=region_modern,
        region_historical=region_historical,
        composition_period_raw=f"{year}(고종 11)" if year else "",
        year=year,
        period=period,
        summary="출판정보 : 『고문서집성』",
    )


def _response(results: list[KoreanstudiesSearchResult]) -> KoreanstudiesSearchResponse:
    return KoreanstudiesSearchResponse(
        total_count=len(results),
        page=1,
        ipp=20,
        results=tuple(results),
    )


# ---------------------------------------------------------------------------
# search() — happy path
# ---------------------------------------------------------------------------


def test_live_search_maps_results_to_heritage_docs() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(1), _result(2)])
    adapter = LiveKoreanstudiesAdapter(client=client)

    matches = adapter.search("음식")
    assert len(matches) == 2
    assert all(isinstance(m, DocumentMatch) for m in matches)
    assert all(isinstance(m.document, HeritageDoc) for m in matches)
    first = matches[0].document
    assert first.external_id == "UCI_DEMO001"
    assert first.institution == "koreanstudies"
    assert first.year == 1874
    assert first.period == "조선후기"
    assert first.region == "서울특별시"  # 현재주소 takes precedence
    assert first.category == "고문서-치부기록류-발기"
    assert "국왕/왕실-의례-발기" in first.summary  # content_category folded in
    assert "작성시기" in first.summary
    assert "고지명" in first.summary  # 한성 ≠ 서울특별시 → kept
    assert first.license == "KOGL-1"


def test_live_search_uses_historical_region_when_modern_absent() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(1, region_modern="", region_historical="한성")])
    adapter = LiveKoreanstudiesAdapter(client=client)
    matches = adapter.search("음식")
    assert matches[0].document.region == "한성"


def test_live_search_strips_hashtag_prefix_from_keyword() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(1)])
    adapter = LiveKoreanstudiesAdapter(client=client)

    adapter.search("#음식")
    call_kwargs = client.search.call_args.kwargs
    assert call_kwargs["query"] == "음식"


def test_live_search_returns_empty_list_for_blank_keyword() -> None:
    client = MagicMock()
    adapter = LiveKoreanstudiesAdapter(client=client)
    assert adapter.search("") == []
    assert adapter.search("   ") == []
    client.search.assert_not_called()


def test_live_search_respects_limit() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(i) for i in range(10)])
    adapter = LiveKoreanstudiesAdapter(client=client)
    matches = adapter.search("음식", limit=3)
    assert len(matches) == 3
    # ipp passed to client is the requested limit (so we don't over-fetch)
    assert client.search.call_args.kwargs["ipp"] == 3


def test_live_search_rank_score_decays_with_position() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(i) for i in range(5)])
    adapter = LiveKoreanstudiesAdapter(client=client)
    matches = adapter.search("음식", limit=5)
    scores = [m.match_score for m in matches]
    assert scores[0] == 0.94
    assert scores == sorted(scores, reverse=True)
    assert scores[-1] >= 0.40


def test_live_search_single_result_uses_top_score() -> None:
    """One-result edge case — top hit should still get the top score."""
    client = MagicMock()
    client.search.return_value = _response([_result(1)])
    adapter = LiveKoreanstudiesAdapter(client=client)
    matches = adapter.search("음식")
    assert matches[0].match_score == 0.94


# ---------------------------------------------------------------------------
# search() — region + period filters
# ---------------------------------------------------------------------------


def test_live_search_period_filter_keeps_matching_records() -> None:
    client = MagicMock()
    client.search.return_value = _response(
        [
            _result(1, year=1903, period="근대"),
            _result(2, year=1670, period="조선후기"),
            _result(3, year=1500, period="조선전기"),
        ]
    )
    adapter = LiveKoreanstudiesAdapter(client=client)
    matches = adapter.search("음식", period="조선후기")
    assert [m.document.year for m in matches] == [1670]


def test_live_search_period_filter_keeps_unknown_period_records() -> None:
    client = MagicMock()
    client.search.return_value = _response(
        [
            _result(1, year=1903, period="근대"),
            _result(2, year=None, period=""),
        ]
    )
    adapter = LiveKoreanstudiesAdapter(client=client)
    matches = adapter.search("음식", period="조선후기")
    # Unknown-period record kept (we'd rather over-include than over-exclude
    # when the upstream metadata was sparse).
    assert [m.document.external_id for m in matches] == ["UCI_DEMO002"]


def test_live_search_region_filter_matches_modern_or_historical() -> None:
    client = MagicMock()
    client.search.return_value = _response(
        [
            _result(1, region_modern="서울특별시", region_historical="한성"),
            _result(2, region_modern="경기도", region_historical="광주"),
            _result(3, region_modern="", region_historical="한성"),
        ]
    )
    adapter = LiveKoreanstudiesAdapter(client=client)
    matches = adapter.search("음식", region="한성")
    ids = [m.document.external_id for m in matches]
    # Records 1 and 3 contain "한성"; record 2 does not.
    assert "UCI_DEMO001" in ids
    assert "UCI_DEMO003" in ids
    assert "UCI_DEMO002" not in ids


def test_live_search_region_filter_keeps_unknown_region_records() -> None:
    client = MagicMock()
    client.search.return_value = _response(
        [
            _result(1, region_modern="서울특별시", region_historical="한성"),
            _result(2, region_modern="", region_historical=""),  # both blank
        ]
    )
    adapter = LiveKoreanstudiesAdapter(client=client)
    matches = adapter.search("음식", region="제주")
    # Unknown-region record kept; known-but-non-matching dropped.
    assert [m.document.external_id for m in matches] == ["UCI_DEMO002"]


# ---------------------------------------------------------------------------
# search() — fallback behaviour
# ---------------------------------------------------------------------------


def test_live_search_falls_back_to_mock_on_api_error() -> None:
    failing_client = MagicMock()
    failing_client.search.side_effect = KoreanstudiesAPIError("upstream timeout")

    fallback = MagicMock()
    fallback.search.return_value = [
        DocumentMatch(
            document=HeritageDoc(
                external_id="mock-1",
                title="mock doc",
                institution="koreanstudies",
                region="전국",
                period="조선후기",
                category="조리서",
                year=1700,
                original_text="",
                summary="",
            ),
            match_score=0.9,
        )
    ]

    adapter = LiveKoreanstudiesAdapter(client=failing_client, fallback=fallback)
    matches = adapter.search("음식", region="전국", period="조선후기", limit=5)

    fallback.search.assert_called_once_with("음식", region="전국", period="조선후기", limit=5)
    assert len(matches) == 1
    assert matches[0].document.external_id == "mock-1"


def test_live_search_empty_results_do_not_trigger_fallback() -> None:
    client = MagicMock()
    client.search.return_value = _response([])

    fallback = MagicMock()
    fallback.search.return_value = [MagicMock()]

    adapter = LiveKoreanstudiesAdapter(client=client, fallback=fallback)
    matches = adapter.search("aaaaaaaa")
    assert matches == []
    fallback.search.assert_not_called()


# ---------------------------------------------------------------------------
# list_seeded() — protocol compliance
# ---------------------------------------------------------------------------


def test_live_adapter_list_seeded_delegates_to_mock() -> None:
    adapter = LiveKoreanstudiesAdapter()
    seeded = adapter.list_seeded()
    # Mock seeds 3 curated docs across the three original spec institutions.
    assert len(seeded) == 3


# ---------------------------------------------------------------------------
# get_heritage_adapter() — factory routing across both live sources
# ---------------------------------------------------------------------------


def _reset_caches() -> None:
    """Both ``get_heritage_adapter`` and ``get_settings`` are lru-cached."""
    from app.config import get_settings

    get_settings.cache_clear()
    get_heritage_adapter.cache_clear()


def test_factory_returns_jangseogak_when_live_source_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    monkeypatch.delenv("HERITAGE_LIVE_SOURCE", raising=False)
    _reset_caches()

    adapter = get_heritage_adapter()
    assert isinstance(adapter, LiveHeritageAdapter)


def test_factory_returns_jangseogak_when_explicitly_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "jangseogak")
    _reset_caches()

    adapter = get_heritage_adapter()
    assert isinstance(adapter, LiveHeritageAdapter)


def test_factory_returns_koreanstudies_when_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "koreanstudies")
    _reset_caches()

    adapter = get_heritage_adapter()
    assert isinstance(adapter, LiveKoreanstudiesAdapter)


def test_factory_returns_mock_regardless_of_live_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If HERITAGE_PROVIDER=mock, the source knob is ignored."""
    monkeypatch.setenv("HERITAGE_PROVIDER", "mock")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "koreanstudies")
    _reset_caches()

    adapter = get_heritage_adapter()
    assert isinstance(adapter, MockHeritageAdapter)


def test_factory_honours_koreanstudies_base_url_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "koreanstudies")
    monkeypatch.setenv("KOREANSTUDIES_BASE_URL", "https://staging.example/portal")
    _reset_caches()

    adapter = get_heritage_adapter()
    assert isinstance(adapter, LiveKoreanstudiesAdapter)
    assert adapter._client._base_url == "https://staging.example/portal"  # type: ignore[attr-defined]
