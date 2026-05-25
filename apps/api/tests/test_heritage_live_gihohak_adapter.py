"""Tests for :class:`LiveGihohakAdapter` and the factory routing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.heritage import (
    LiveGihohakAdapter,
    LiveHeritageAdapter,
    LiveKoreanstudiesAdapter,
    LiveNlkAdapter,
    MockHeritageAdapter,
    get_heritage_adapter,
)
from app.services.heritage.base import DocumentMatch, HeritageDoc
from app.services.heritage.gihohak import (
    GihohakAPIError,
    GihohakSearchResponse,
    GihohakSearchResult,
)
from app.services.heritage.live_gihohak import GIHOHAK_REGION_LABEL


def _result(
    idx: int,
    *,
    data_type: str = "OB",
    data_type_name: str = "고서",
    year: int | None = 1670,
    period: str = "조선후기",
    created_raw: str = "1670",
    relation_date: str = "경술",
    recommended: bool = False,
    class_full_name: str = "잡저류>음식류",
    alt_title: str = "飮食方文",
    abstract: str = "송시열 문중에 전해온 음식 조리법.",
) -> GihohakSearchResult:
    return GihohakSearchResult(
        external_id=f"OB_{idx:08d}",
        data_type=data_type,
        data_type_name=data_type_name,
        title=f"음식방문 {idx}",
        alt_title=alt_title,
        creator=f"송시열 {idx}",
        created_raw=created_raw,
        year=year,
        period=period,
        relation_date=relation_date,
        recommended=recommended,
        class_full_name=class_full_name,
        uci=f"G001+KR03-7001144.180101.B0.OB_{idx:08d}",
        detail_url=f"http://giho.cnu.ac.kr/shr/gihoSearchUserDetail.do?id={idx}",
        abstract=abstract,
    )


def _response(results: list[GihohakSearchResult]) -> GihohakSearchResponse:
    return GihohakSearchResponse(
        total_count=len(results),
        type_filter="OB",
        target="all",
        keyword="음식",
        page=1,
        page_size=10,
        results=tuple(results),
    )


# ---------------------------------------------------------------------------
# search() — happy path
# ---------------------------------------------------------------------------


def test_live_search_maps_results_to_heritage_docs() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(1), _result(2)])
    adapter = LiveGihohakAdapter(client=client)

    matches = adapter.search("음식")
    assert len(matches) == 2
    assert all(isinstance(m, DocumentMatch) for m in matches)
    assert all(isinstance(m.document, HeritageDoc) for m in matches)
    first = matches[0].document
    assert first.external_id == "OB_00000001"
    assert first.institution == "gihohak"
    assert first.region == GIHOHAK_REGION_LABEL  # "충청"
    assert first.year == 1670
    assert first.period == "조선후기"
    # category uses the full classification hierarchy when available
    assert first.category == "잡저류>음식류"
    # summary should include creator, alt title, year, classification, type
    assert "송시열" in first.summary
    assert "한자명: 飮食方文" in first.summary
    assert "생성년도: 1670" in first.summary
    assert "간지: 경술" in first.summary
    assert "분류: 잡저류>음식류" in first.summary
    assert "유형: 고서" in first.summary
    assert first.license == "KOGL-1"


def test_live_search_folds_recommended_flag_into_summary() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(1, recommended=True)])
    adapter = LiveGihohakAdapter(client=client)
    matches = adapter.search("음식")
    assert "추천 자료" in matches[0].document.summary


def test_live_search_skips_alt_title_when_identical_to_title() -> None:
    client = MagicMock()
    # Force a title-matching alt_title by manually building the result
    custom = _result(1, alt_title="음식방문 1")  # matches `f"음식방문 {idx}"`
    client.search.return_value = _response([custom])
    adapter = LiveGihohakAdapter(client=client)
    matches = adapter.search("음식")
    assert "한자명:" not in matches[0].document.summary


def test_live_search_falls_back_to_data_type_name_when_class_missing() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(1, class_full_name="")])
    adapter = LiveGihohakAdapter(client=client)
    matches = adapter.search("음식")
    # category falls back to data_type_name when class_full_name is empty
    assert matches[0].document.category == "고서"


def test_live_search_handles_unknown_year_with_미상_marker() -> None:
    client = MagicMock()
    client.search.return_value = _response(
        [_result(1, year=None, period="", created_raw="미상", relation_date="미상")]
    )
    adapter = LiveGihohakAdapter(client=client)
    matches = adapter.search("음식")
    doc = matches[0].document
    assert doc.year is None
    assert doc.period == ""
    assert "생성년도: 미상" in doc.summary
    # When created_raw == relation_date, don't duplicate.
    assert doc.summary.count("미상") == 1


def test_live_search_strips_hashtag_prefix_from_keyword() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(1)])
    adapter = LiveGihohakAdapter(client=client)

    adapter.search("#음식")
    call_kwargs = client.search.call_args.kwargs
    assert call_kwargs["query"] == "음식"


def test_live_search_returns_empty_list_for_blank_keyword() -> None:
    client = MagicMock()
    adapter = LiveGihohakAdapter(client=client)
    assert adapter.search("") == []
    assert adapter.search("   ") == []
    client.search.assert_not_called()


def test_live_search_respects_limit() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(i) for i in range(10)])
    adapter = LiveGihohakAdapter(client=client)
    matches = adapter.search("음식", limit=3)
    assert len(matches) == 3
    assert client.search.call_args.kwargs["page_size"] == 3


def test_live_search_rank_score_decays_with_position() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(i) for i in range(5)])
    adapter = LiveGihohakAdapter(client=client)
    matches = adapter.search("음식", limit=5)
    scores = [m.match_score for m in matches]
    assert scores[0] == 0.94
    assert scores == sorted(scores, reverse=True)
    assert scores[-1] >= 0.40


def test_live_search_single_result_uses_top_score() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(1)])
    adapter = LiveGihohakAdapter(client=client)
    matches = adapter.search("음식")
    assert matches[0].match_score == 0.94


# ---------------------------------------------------------------------------
# search() — filters
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
    adapter = LiveGihohakAdapter(client=client)
    matches = adapter.search("음식", period="조선후기")
    assert [m.document.year for m in matches] == [1670]


def test_live_search_period_filter_keeps_unknown_period_records() -> None:
    client = MagicMock()
    client.search.return_value = _response(
        [
            _result(1, year=1903, period="근대"),
            _result(2, year=None, period="", created_raw="미상"),
        ]
    )
    adapter = LiveGihohakAdapter(client=client)
    matches = adapter.search("음식", period="조선후기")
    # Unknown-period record kept (over-include policy)
    assert [m.document.external_id for m in matches] == ["OB_00000002"]


def test_live_search_region_filter_충청_keeps_all_records() -> None:
    """기호유학 records all carry region="충청" — explicit 충청 filter keeps them."""
    client = MagicMock()
    client.search.return_value = _response([_result(1), _result(2)])
    adapter = LiveGihohakAdapter(client=client)
    matches = adapter.search("음식", region="충청")
    assert len(matches) == 2


def test_live_search_region_filter_other_region_drops_all() -> None:
    """기호유학 covers only 충청권 — asking for 제주 must yield zero hits."""
    client = MagicMock()
    client.search.return_value = _response([_result(1), _result(2)])
    adapter = LiveGihohakAdapter(client=client)
    matches = adapter.search("음식", region="제주")
    assert matches == []


def test_live_search_region_filter_empty_string_keeps_all_records() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(1), _result(2)])
    adapter = LiveGihohakAdapter(client=client)
    matches = adapter.search("음식", region="")
    assert len(matches) == 2


# ---------------------------------------------------------------------------
# search() — fallback behaviour
# ---------------------------------------------------------------------------


def test_live_search_falls_back_to_mock_on_api_error() -> None:
    failing_client = MagicMock()
    failing_client.search.side_effect = GihohakAPIError("upstream timeout")

    fallback = MagicMock()
    fallback.search.return_value = [
        DocumentMatch(
            document=HeritageDoc(
                external_id="mock-1",
                title="mock doc",
                institution="gihohak",
                region="충청",
                period="조선후기",
                category="고서",
                year=1700,
                original_text="",
                summary="",
            ),
            match_score=0.9,
        )
    ]

    adapter = LiveGihohakAdapter(client=failing_client, fallback=fallback)
    matches = adapter.search("음식", region="충청", period="조선후기", limit=5)

    fallback.search.assert_called_once_with("음식", region="충청", period="조선후기", limit=5)
    assert len(matches) == 1
    assert matches[0].document.external_id == "mock-1"


def test_live_search_empty_results_do_not_trigger_fallback() -> None:
    client = MagicMock()
    client.search.return_value = _response([])

    fallback = MagicMock()
    fallback.search.return_value = [MagicMock()]

    adapter = LiveGihohakAdapter(client=client, fallback=fallback)
    matches = adapter.search("aaaaaaaa")
    assert matches == []
    fallback.search.assert_not_called()


# ---------------------------------------------------------------------------
# list_seeded() — protocol compliance
# ---------------------------------------------------------------------------


def test_live_adapter_list_seeded_delegates_to_mock() -> None:
    adapter = LiveGihohakAdapter(client=MagicMock())
    seeded = adapter.list_seeded()
    assert len(seeded) == 3


def test_live_adapter_constructs_default_client_when_none_given() -> None:
    """No-arg construction is supported because 기호유학 has no auth requirement."""
    adapter = LiveGihohakAdapter()
    # If construction succeeded with no client kwarg, the default-client branch ran.
    assert adapter._client is not None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# get_heritage_adapter() — factory routing across all four live sources
# ---------------------------------------------------------------------------


def _reset_caches() -> None:
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


def test_factory_returns_koreanstudies_when_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "koreanstudies")
    _reset_caches()
    adapter = get_heritage_adapter()
    assert isinstance(adapter, LiveKoreanstudiesAdapter)


def test_factory_returns_nlk_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "nlk")
    monkeypatch.setenv("NLK_API_KEY", "test-key-value")
    _reset_caches()
    adapter = get_heritage_adapter()
    assert isinstance(adapter, LiveNlkAdapter)


def test_factory_returns_gihohak_when_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "gihohak")
    _reset_caches()
    adapter = get_heritage_adapter()
    assert isinstance(adapter, LiveGihohakAdapter)


def test_factory_returns_mock_regardless_of_live_source_when_provider_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "mock")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "gihohak")
    _reset_caches()
    adapter = get_heritage_adapter()
    assert isinstance(adapter, MockHeritageAdapter)


def test_factory_honours_gihohak_base_url_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "gihohak")
    monkeypatch.setenv("GIHOHAK_BASE_URL", "https://staging.example/giho")
    _reset_caches()
    adapter = get_heritage_adapter()
    assert isinstance(adapter, LiveGihohakAdapter)
    assert adapter._client._base_url == "https://staging.example/giho"  # type: ignore[attr-defined]


def test_factory_literal_invariant_covers_four_sources() -> None:
    """Sanity check: the Literal type guards env input — all four sources allowed."""
    from app.config import get_settings

    _reset_caches()
    settings = get_settings()
    assert settings.heritage_live_source in {
        "jangseogak",
        "koreanstudies",
        "nlk",
        "gihohak",
    }
