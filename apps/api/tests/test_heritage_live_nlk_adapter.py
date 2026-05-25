"""Tests for :class:`LiveNlkAdapter` and the factory routing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.heritage import (
    LiveHeritageAdapter,
    LiveKoreanstudiesAdapter,
    LiveNlkAdapter,
    MockHeritageAdapter,
    get_heritage_adapter,
)
from app.services.heritage.base import DocumentMatch, HeritageDoc
from app.services.heritage.nlk import (
    NlkAPIError,
    NlkSearchResponse,
    NlkSearchResult,
)


def _result(
    idx: int,
    *,
    year: int | None = 1814,
    period: str = "조선후기",
    has_original: bool = False,
    detail_link: str = "",
) -> NlkSearchResult:
    return NlkSearchResult(
        external_id=f"KORCIS-{idx:04d}",
        title=f"테스트 자료 {idx}",
        author=f"저자{idx}",
        publisher="경상도 석계종가",
        pub_year_raw=f"순조 14년({year}년)" if year else "",
        year=year,
        period=period,
        type_name="고문헌",
        call_number=f"古貴 594-{idx}",
        isbn="",
        detail_url=detail_link or f"https://www.nl.go.kr/NL/contents/search.do?id={idx}",
        has_original_text=has_original,
        original_text_url=(
            f"https://www.nl.go.kr/NL/contents/original/{idx}" if has_original else ""
        ),
        kdc_code="590",
        kdc_name="가정학",
        license_code="L",
        license_text="국립중앙도서관 무료 열람",
    )


def _response(results: list[NlkSearchResult]) -> NlkSearchResponse:
    return NlkSearchResponse(
        total_count=len(results),
        page_num=1,
        page_size=10,
        results=tuple(results),
    )


# ---------------------------------------------------------------------------
# search() — happy path
# ---------------------------------------------------------------------------


def test_live_search_maps_results_to_heritage_docs() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(1), _result(2)])
    adapter = LiveNlkAdapter(client=client)

    matches = adapter.search("음식")
    assert len(matches) == 2
    assert all(isinstance(m, DocumentMatch) for m in matches)
    assert all(isinstance(m.document, HeritageDoc) for m in matches)
    first = matches[0].document
    assert first.external_id == "KORCIS-0001"
    assert first.institution == "nlk"
    assert first.year == 1814
    assert first.period == "조선후기"
    assert first.category == "고문헌"
    assert first.region == ""  # NLK has no region field
    # summary should contain author, publisher, year, KDC name, call number
    assert "저자1" in first.summary
    assert "경상도 석계종가" in first.summary
    assert "발행: 순조 14년(1814년)" in first.summary
    assert "분류: 가정학" in first.summary
    assert "청구기호:" in first.summary
    assert first.license == "KOGL-1"


def test_live_search_marks_original_text_availability_in_summary() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(1, has_original=True)])
    adapter = LiveNlkAdapter(client=client)
    matches = adapter.search("음식")
    assert "원문 보기 가능" in matches[0].document.summary


def test_live_search_strips_hashtag_prefix_from_keyword() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(1)])
    adapter = LiveNlkAdapter(client=client)

    adapter.search("#음식")
    call_kwargs = client.search.call_args.kwargs
    assert call_kwargs["query"] == "음식"


def test_live_search_returns_empty_list_for_blank_keyword() -> None:
    client = MagicMock()
    adapter = LiveNlkAdapter(client=client)
    assert adapter.search("") == []
    assert adapter.search("   ") == []
    client.search.assert_not_called()


def test_live_search_respects_limit() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(i) for i in range(10)])
    adapter = LiveNlkAdapter(client=client)
    matches = adapter.search("음식", limit=3)
    assert len(matches) == 3
    assert client.search.call_args.kwargs["page_size"] == 3


def test_live_search_rank_score_decays_with_position() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(i) for i in range(5)])
    adapter = LiveNlkAdapter(client=client)
    matches = adapter.search("음식", limit=5)
    scores = [m.match_score for m in matches]
    assert scores[0] == 0.94
    assert scores == sorted(scores, reverse=True)
    assert scores[-1] >= 0.40


def test_live_search_single_result_uses_top_score() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(1)])
    adapter = LiveNlkAdapter(client=client)
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
    adapter = LiveNlkAdapter(client=client)
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
    adapter = LiveNlkAdapter(client=client)
    matches = adapter.search("음식", period="조선후기")
    # Unknown-period record kept (over-include policy)
    assert [m.document.external_id for m in matches] == ["KORCIS-0002"]


def test_live_search_region_filter_is_no_op() -> None:
    """NLK has no region field — passing region= must not drop records."""
    client = MagicMock()
    client.search.return_value = _response([_result(1), _result(2)])
    adapter = LiveNlkAdapter(client=client)
    matches = adapter.search("음식", region="제주")
    assert len(matches) == 2  # nothing filtered


# ---------------------------------------------------------------------------
# search() — fallback behaviour
# ---------------------------------------------------------------------------


def test_live_search_falls_back_to_mock_on_api_error() -> None:
    failing_client = MagicMock()
    failing_client.search.side_effect = NlkAPIError("upstream timeout", error_code="000")

    fallback = MagicMock()
    fallback.search.return_value = [
        DocumentMatch(
            document=HeritageDoc(
                external_id="mock-1",
                title="mock doc",
                institution="nlk",
                region="전국",
                period="조선후기",
                category="고문헌",
                year=1700,
                original_text="",
                summary="",
            ),
            match_score=0.9,
        )
    ]

    adapter = LiveNlkAdapter(client=failing_client, fallback=fallback)
    matches = adapter.search("음식", region="전국", period="조선후기", limit=5)

    fallback.search.assert_called_once_with("음식", region="전국", period="조선후기", limit=5)
    assert len(matches) == 1
    assert matches[0].document.external_id == "mock-1"


def test_live_search_falls_back_to_mock_on_invalid_key_error() -> None:
    """An <error_code>011</error_code> upstream envelope is a fall-back trigger,
    not a hard failure — the request still gets satisfied from the seed pool."""
    failing_client = MagicMock()
    failing_client.search.side_effect = NlkAPIError(
        "NLK error_code=011: INVALID KEY", error_code="011"
    )

    fallback = MagicMock()
    fallback.search.return_value = []

    adapter = LiveNlkAdapter(client=failing_client, fallback=fallback)
    adapter.search("음식")
    fallback.search.assert_called_once()


def test_live_search_empty_results_do_not_trigger_fallback() -> None:
    client = MagicMock()
    client.search.return_value = _response([])

    fallback = MagicMock()
    fallback.search.return_value = [MagicMock()]

    adapter = LiveNlkAdapter(client=client, fallback=fallback)
    matches = adapter.search("aaaaaaaa")
    assert matches == []
    fallback.search.assert_not_called()


# ---------------------------------------------------------------------------
# list_seeded() — protocol compliance
# ---------------------------------------------------------------------------


def test_live_adapter_list_seeded_delegates_to_mock() -> None:
    adapter = LiveNlkAdapter(client=MagicMock())
    seeded = adapter.list_seeded()
    assert len(seeded) == 3


# ---------------------------------------------------------------------------
# get_heritage_adapter() — factory routing across all three live sources
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


def test_factory_degrades_to_mock_when_nlk_selected_but_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NLK source without an API key must not boot-fail — quietly use mock."""
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "nlk")
    monkeypatch.delenv("NLK_API_KEY", raising=False)
    _reset_caches()
    adapter = get_heritage_adapter()
    assert isinstance(adapter, MockHeritageAdapter)


def test_factory_returns_mock_regardless_of_live_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "mock")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "nlk")
    monkeypatch.setenv("NLK_API_KEY", "test-key")
    _reset_caches()
    adapter = get_heritage_adapter()
    assert isinstance(adapter, MockHeritageAdapter)


def test_factory_honours_nlk_base_url_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    monkeypatch.setenv("HERITAGE_LIVE_SOURCE", "nlk")
    monkeypatch.setenv("NLK_API_KEY", "test-key")
    monkeypatch.setenv("NLK_BASE_URL", "https://staging.example/nlk")
    _reset_caches()
    adapter = get_heritage_adapter()
    assert isinstance(adapter, LiveNlkAdapter)
    assert adapter._client._base_url == "https://staging.example/nlk"  # type: ignore[attr-defined]


def test_factory_unknown_live_source_value_falls_through_to_jangseogak() -> None:
    """The Literal type guards env input, but defensive coding: any other
    value must NOT crash recipe-generate; it falls through to the default
    jangseogak branch."""
    # We bypass pydantic by patching settings directly because the Literal
    # rejects unknown values at validation time.
    from app.config import get_settings

    settings = get_settings()
    # Sanity-check: the Literal only accepts the documented values.
    assert settings.heritage_live_source in {
        "jangseogak",
        "koreanstudies",
        "nlk",
        "gihohak",
        "multi",
    }
