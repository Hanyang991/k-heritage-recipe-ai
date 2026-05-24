"""Tests for :class:`LiveHeritageAdapter` and the factory routing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.heritage import (
    LiveHeritageAdapter,
    MockHeritageAdapter,
    get_heritage_adapter,
)
from app.services.heritage.base import DocumentMatch, HeritageDoc
from app.services.heritage.jangseogak import (
    JangseogakAPIError,
    JangseogakSearchResponse,
    JangseogakSearchResult,
)


def _result(idx: int, *, year: int | None = 1903, period: str = "근대") -> JangseogakSearchResult:
    return JangseogakSearchResult(
        external_id=f"JSG_DEMO{idx:03d}",
        title=f"테스트 자료 {idx}",
        author="익명",
        type_category="고문서/의례류/발기(發記)",
        subject_category="국왕·왕실/의례",
        call_number=f"RD0{idx:04d}",
        mf_number="MF35-0001",
        composition_period_raw=f"{year}(光武 1)" if year else "",
        year=year,
        period=period,
        detail_url=f"https://jsg.aks.ac.kr/dir/view?dataId=JSG_DEMO{idx:03d}",
    )


def _response(results: list[JangseogakSearchResult]) -> JangseogakSearchResponse:
    return JangseogakSearchResponse(
        total_count=len(results),
        start_index=0,
        page_unit=20,
        results=tuple(results),
    )


# ---------------------------------------------------------------------------
# search() — happy path
# ---------------------------------------------------------------------------


def test_live_search_maps_results_to_heritage_docs() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(1), _result(2)])
    adapter = LiveHeritageAdapter(client=client)

    matches = adapter.search("음식")
    assert len(matches) == 2
    assert all(isinstance(m, DocumentMatch) for m in matches)
    assert all(isinstance(m.document, HeritageDoc) for m in matches)
    first = matches[0].document
    assert first.external_id == "JSG_DEMO001"
    assert first.institution == "jangseogak"
    assert first.year == 1903
    assert first.period == "근대"
    assert first.category.startswith("고문서/의례류")
    assert first.summary  # populated from type_category + author + 작성시기 + 청구기호
    assert first.license == "KOGL-1"


def test_live_search_strips_hashtag_prefix_from_keyword() -> None:
    """Recipe-generate sometimes forwards ``#태그`` style keywords."""
    client = MagicMock()
    client.search.return_value = _response([_result(1)])
    adapter = LiveHeritageAdapter(client=client)

    adapter.search("#음식")
    call_kwargs = client.search.call_args.kwargs
    assert call_kwargs["query"] == "음식"


def test_live_search_returns_empty_list_for_blank_keyword() -> None:
    client = MagicMock()
    adapter = LiveHeritageAdapter(client=client)
    assert adapter.search("") == []
    assert adapter.search("   ") == []
    client.search.assert_not_called()


def test_live_search_respects_limit() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(i) for i in range(10)])
    adapter = LiveHeritageAdapter(client=client)
    matches = adapter.search("음식", limit=3)
    assert len(matches) == 3
    # page_unit passed to client is the requested limit (so we don't
    # over-fetch when only 3 are needed).
    assert client.search.call_args.kwargs["page_unit"] == 3


def test_live_search_rank_score_decays_with_position() -> None:
    client = MagicMock()
    client.search.return_value = _response([_result(i) for i in range(5)])
    adapter = LiveHeritageAdapter(client=client)
    matches = adapter.search("음식", limit=5)
    scores = [m.match_score for m in matches]
    assert scores[0] == 0.94  # top hit
    assert scores == sorted(scores, reverse=True)  # strictly non-increasing
    assert scores[-1] >= 0.40  # floor


# ---------------------------------------------------------------------------
# search() — period filter
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
    adapter = LiveHeritageAdapter(client=client)
    matches = adapter.search("음식", period="조선후기")
    assert [m.document.year for m in matches] == [1670]


def test_live_search_period_filter_keeps_unknown_period_records() -> None:
    """Records with no parseable year shouldn't be filtered out — period=''
    means 'we couldn't tell', not 'definitely not match'."""
    client = MagicMock()
    client.search.return_value = _response(
        [
            _result(1, year=1903, period="근대"),
            _result(2, year=None, period=""),
        ]
    )
    adapter = LiveHeritageAdapter(client=client)
    matches = adapter.search("음식", period="조선후기")
    # Unknown-period record kept (we'd rather over-include than over-exclude
    # when the upstream gave us nothing to filter on).
    assert [m.document.external_id for m in matches] == ["JSG_DEMO002"]


# ---------------------------------------------------------------------------
# search() — fallback behaviour
# ---------------------------------------------------------------------------


def test_live_search_falls_back_to_mock_on_api_error() -> None:
    failing_client = MagicMock()
    failing_client.search.side_effect = JangseogakAPIError("upstream timeout")

    fallback = MagicMock()
    fallback.search.return_value = [
        DocumentMatch(
            document=HeritageDoc(
                external_id="mock-1",
                title="mock doc",
                institution="jangseogak",
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

    adapter = LiveHeritageAdapter(client=failing_client, fallback=fallback)
    matches = adapter.search("음식", region="전국", period="조선후기", limit=5)

    fallback.search.assert_called_once_with("음식", region="전국", period="조선후기", limit=5)
    assert len(matches) == 1
    assert matches[0].document.external_id == "mock-1"


def test_live_search_empty_results_do_not_trigger_fallback() -> None:
    """Empty results are valid information — do not pretend the API failed."""
    client = MagicMock()
    client.search.return_value = _response([])

    fallback = MagicMock()
    fallback.search.return_value = [MagicMock()]  # would be returned if fallback fired

    adapter = LiveHeritageAdapter(client=client, fallback=fallback)
    matches = adapter.search("aaaaaaaa")  # plausible-but-empty result
    assert matches == []
    fallback.search.assert_not_called()


# ---------------------------------------------------------------------------
# list_seeded() — protocol compliance
# ---------------------------------------------------------------------------


def test_live_adapter_list_seeded_delegates_to_mock() -> None:
    adapter = LiveHeritageAdapter()  # default fallback = MockHeritageAdapter
    seeded = adapter.list_seeded()
    # Mock seeds 3 curated docs (음식디미방 / 규합총서 / 전주 향토음료)
    assert len(seeded) == 3
    assert {d.institution for d in seeded} == {"jangseogak", "nfm", "culture"}


# ---------------------------------------------------------------------------
# get_heritage_adapter() — factory routing
# ---------------------------------------------------------------------------


def test_factory_returns_mock_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "mock")
    get_heritage_adapter.cache_clear()
    from app.config import get_settings

    get_settings.cache_clear()

    adapter = get_heritage_adapter()
    assert isinstance(adapter, MockHeritageAdapter)


def test_factory_returns_live_when_provider_is_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    get_heritage_adapter.cache_clear()
    from app.config import get_settings

    get_settings.cache_clear()

    adapter = get_heritage_adapter()
    assert isinstance(adapter, LiveHeritageAdapter)


def test_factory_honours_jangseogak_base_url_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERITAGE_PROVIDER", "live")
    monkeypatch.setenv("JANGSEOGAK_BASE_URL", "https://staging.example/api")
    get_heritage_adapter.cache_clear()
    from app.config import get_settings

    get_settings.cache_clear()

    adapter = get_heritage_adapter()
    assert isinstance(adapter, LiveHeritageAdapter)
    # Internal client base URL is stripped of trailing slash by the client
    assert adapter._client._base_url == "https://staging.example/api"  # type: ignore[attr-defined]
