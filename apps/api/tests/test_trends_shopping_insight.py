"""Unit tests for ``NaverShoppingInsightAdapter`` + ``NaverShoppingInsightDiscovery``."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.trends import (
    CuratedWatchlistDiscovery,
    NaverShoppingInsightAdapter,
    NaverShoppingInsightDiscovery,
    TrendsAdapterError,
    get_trend_discovery,
)
from app.services.trends.base import TrendDataPoint, TrendKeywordSeries
from app.services.trends.mock import MockTrendsAdapter
from app.services.trends.shopping_insight import (
    FOOD_CATEGORY_CODE,
    _chunk,
    _parse_response,
)


def _mock_response(status_code: int, json_body: dict[str, Any] | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = "" if json_body is None else str(json_body)
    return resp


# ---------------------------------------------------------------------------
# Adapter — request shape
# ---------------------------------------------------------------------------


def test_adapter_posts_category_keywords_endpoint() -> None:
    adapter = NaverShoppingInsightAdapter(client_id="id", client_secret="sec")
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, {"results": []})
        adapter.fetch_series(["쑥라떼"], date(2025, 1, 1), date(2025, 1, 31))
        url = post.call_args.args[0]
        assert url.endswith("/v1/datalab/shopping/category/keywords")


def test_adapter_request_body_uses_category_and_keyword_shape() -> None:
    adapter = NaverShoppingInsightAdapter(
        client_id="id", client_secret="sec", category_code="50000006"
    )
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, {"results": []})
        adapter.fetch_series(
            ["쑥라떼", "흑임자라떼"],
            date(2025, 1, 1),
            date(2025, 1, 31),
            time_unit="week",
        )
        body = post.call_args.kwargs["json"]
        # Shopping Insight uses `category` + `keyword: [{name, param}]`
        # (DataLab Search uses `keywordGroups: [{groupName, keywords}]`)
        assert body["category"] == "50000006"
        assert body["timeUnit"] == "week"
        assert body["startDate"] == "2025-01-01"
        assert body["endDate"] == "2025-01-31"
        assert body["keyword"] == [
            {"name": "쑥라떼", "param": ["쑥라떼"]},
            {"name": "흑임자라떼", "param": ["흑임자라떼"]},
        ]


def test_adapter_sends_auth_headers() -> None:
    adapter = NaverShoppingInsightAdapter(client_id="my-id", client_secret="my-secret")
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, {"results": []})
        adapter.fetch_series(["a"], date(2025, 1, 1), date(2025, 1, 31))
        headers = post.call_args.kwargs["headers"]
        assert headers["X-Naver-Client-Id"] == "my-id"
        assert headers["X-Naver-Client-Secret"] == "my-secret"


def test_adapter_chunks_into_multiple_requests_at_5_groups() -> None:
    adapter = NaverShoppingInsightAdapter(client_id="id", client_secret="sec")
    keywords = [f"k{i}" for i in range(12)]
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, {"results": []})
        adapter.fetch_series(keywords, date(2025, 1, 1), date(2025, 1, 31))
        assert post.call_count == 3
        first_body = post.call_args_list[0].kwargs["json"]
        assert [kw["name"] for kw in first_body["keyword"]] == keywords[:5]


def test_adapter_empty_keywords_returns_empty_no_call() -> None:
    adapter = NaverShoppingInsightAdapter(client_id="id", client_secret="sec")
    with patch("httpx.Client.post") as post:
        result = adapter.fetch_series([], date(2025, 1, 1), date(2025, 1, 31))
        post.assert_not_called()
        assert result == []


def test_adapter_uses_default_food_category_code() -> None:
    adapter = NaverShoppingInsightAdapter(client_id="id", client_secret="sec")
    assert adapter.category_code == FOOD_CATEGORY_CODE == "50000006"


# ---------------------------------------------------------------------------
# Adapter — error handling
# ---------------------------------------------------------------------------


def test_adapter_raises_on_401() -> None:
    adapter = NaverShoppingInsightAdapter(client_id="bad", client_secret="bad")
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(401, {"errorMessage": "Unauthorized"})
        with pytest.raises(TrendsAdapterError, match="401"):
            adapter.fetch_series(["a"], date(2025, 1, 1), date(2025, 1, 31))


def test_adapter_403_mentions_shopping_insight_toggle() -> None:
    """403 (vs 401) on this endpoint usually means the API is not enabled."""
    adapter = NaverShoppingInsightAdapter(client_id="id", client_secret="sec")
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(403, {"errorMessage": "Forbidden"})
        with pytest.raises(TrendsAdapterError, match="쇼핑인사이트"):
            adapter.fetch_series(["a"], date(2025, 1, 1), date(2025, 1, 31))


def test_adapter_raises_on_429() -> None:
    adapter = NaverShoppingInsightAdapter(client_id="id", client_secret="sec")
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(429, {"errorMessage": "Quota"})
        with pytest.raises(TrendsAdapterError, match="429"):
            adapter.fetch_series(["a"], date(2025, 1, 1), date(2025, 1, 31))


def test_adapter_wraps_transport_errors() -> None:
    adapter = NaverShoppingInsightAdapter(client_id="id", client_secret="sec")
    with patch("httpx.Client.post", side_effect=httpx.ConnectError("boom")):
        with pytest.raises(TrendsAdapterError, match="Naver Shopping Insight request failed"):
            adapter.fetch_series(["a"], date(2025, 1, 1), date(2025, 1, 31))


# ---------------------------------------------------------------------------
# Adapter — parsing
# ---------------------------------------------------------------------------


def test_chunk_splits_into_groups_of_5() -> None:
    keywords = [f"k{i}" for i in range(12)]
    chunks = _chunk(keywords, 5)
    assert [len(c) for c in chunks] == [5, 5, 2]
    assert sum(chunks, []) == keywords


def test_parse_response_extracts_keyword_series() -> None:
    payload: dict[str, Any] = {
        "results": [
            {
                "title": "쑥라떼",
                "category": "50000006",
                "keyword": ["쑥라떼"],
                "data": [
                    {"period": "2025-02-24", "ratio": 86.0},
                    {"period": "2025-03-03", "ratio": 100.0},
                ],
            }
        ]
    }
    series = _parse_response(payload)
    assert len(series) == 1
    assert series[0].keyword == "쑥라떼"
    assert series[0].data[0].period == date(2025, 2, 24)
    assert series[0].data[0].ratio == pytest.approx(86.0)


def test_parse_response_skips_malformed_rows() -> None:
    payload: dict[str, Any] = {
        "results": [
            {
                "title": "x",
                "data": [
                    {"period": "2025-01-01", "ratio": 10},
                    {"period": "not-a-date", "ratio": 99},
                    {"period": "2025-01-08"},
                    {"period": "2025-01-15", "ratio": 20},
                ],
            }
        ]
    }
    series = _parse_response(payload)
    assert [p.period for p in series[0].data] == [date(2025, 1, 1), date(2025, 1, 15)]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class _FakeAdapter:
    def __init__(self, series: list[TrendKeywordSeries]) -> None:
        self._series = series
        self.calls: list[tuple[list[str], date, date, str]] = []

    def fetch_series(self, keywords, start, end, time_unit="week"):  # type: ignore[no-untyped-def]
        self.calls.append((list(keywords), start, end, time_unit))
        return list(self._series)


def _series(keyword: str, points: list[tuple[date, float]]) -> TrendKeywordSeries:
    return TrendKeywordSeries(
        keyword=keyword,
        data=tuple(TrendDataPoint(period=d, ratio=r) for d, r in points),
    )


def test_discovery_labels_source_as_shopping_insight() -> None:
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter([_series("쑥라떼", [(week_a, 50.0), (week_b, 80.0)])])
    discovery = NaverShoppingInsightDiscovery(adapter, ["쑥라떼"], weeks=4)

    result = discovery.discover(today=week_b, limit=10)
    assert len(result) == 1
    assert result[0].source == "shopping_insight"


def test_discovery_ranks_by_blended_popular_plus_rise() -> None:
    """Same blended formula as CuratedWatchlistDiscovery so PR #14 merging is fair."""
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter(
        [
            _series("쑥라떼", [(week_a, 50.0), (week_b, 80.0)]),
            _series("대추차", [(week_a, 90.0), (week_b, 60.0)]),
            _series("수정과", [(week_a, 30.0), (week_b, 30.0)]),
        ]
    )
    discovery = NaverShoppingInsightDiscovery(adapter, ["쑥라떼", "대추차", "수정과"], weeks=4)

    result = discovery.discover(today=week_b, limit=10)

    # 쑥라떼: 0.4*80 + 0.6*60.0   = 68.0
    # 수정과: 0.4*30 + 0.6*0      = 12.0
    # 대추차: 0.4*60 + 0.6*-33.33 = 4.0  (rise clamped within [-100, 200])
    assert [d.keyword for d in result] == ["쑥라떼", "수정과", "대추차"]
    assert result[0].score == pytest.approx(68.0)


def test_discovery_filters_zero_volume_keywords() -> None:
    """Shopping Insight returns flat-zero for keywords with no shopping queries."""
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter(
        [
            _series("쑥라떼", [(week_a, 50.0), (week_b, 80.0)]),
            _series("전혀안팔리는음료", [(week_a, 0.0), (week_b, 0.0)]),
        ]
    )
    discovery = NaverShoppingInsightDiscovery(adapter, ["쑥라떼", "전혀안팔리는음료"], weeks=4)

    result = discovery.discover(today=week_b, limit=10)
    assert [d.keyword for d in result] == ["쑥라떼"]


def test_discovery_keeps_keywords_with_any_nonzero_point() -> None:
    """Even one non-zero point in the window means we shouldn't drop it."""
    week_a, week_b, week_c = date(2025, 4, 28), date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter([_series("느린성장", [(week_a, 0.0), (week_b, 5.0), (week_c, 0.0)])])
    discovery = NaverShoppingInsightDiscovery(adapter, ["느린성장"], weeks=4)

    result = discovery.discover(today=week_c, limit=10)
    assert [d.keyword for d in result] == ["느린성장"]


def test_discovery_uses_default_watchlist_when_no_candidates() -> None:
    from app.services.trends.watchlist import DEFAULT_WATCHLIST

    adapter = _FakeAdapter([])
    discovery = NaverShoppingInsightDiscovery(adapter)
    assert discovery.candidates == DEFAULT_WATCHLIST


def test_discovery_caps_at_limit() -> None:
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter(
        [_series(f"kw{i}", [(week_a, float(i + 1)), (week_b, float(i + 2))]) for i in range(10)]
    )
    discovery = NaverShoppingInsightDiscovery(adapter, [f"kw{i}" for i in range(10)])

    result = discovery.discover(today=week_b, limit=3)
    assert len(result) == 3


def test_discovery_clamps_extreme_rise() -> None:
    """Rise % is clamped to [-100, 200] (inherits from _blended_score)."""
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter(
        [
            _series("저점반등", [(week_a, 0.5), (week_b, 5.0)]),  # +900%, clamped to +200
            _series("안정", [(week_a, 50.0), (week_b, 50.0)]),  # 0% rise
        ]
    )
    discovery = NaverShoppingInsightDiscovery(adapter, ["저점반등", "안정"])

    result = discovery.discover(today=week_b, limit=10)
    # 저점반등: 0.4*5  + 0.6*200 = 2 + 120 = 122
    # 안정    : 0.4*50 + 0.6*0   = 20
    assert [d.keyword for d in result] == ["저점반등", "안정"]
    assert result[0].score == pytest.approx(122.0)


# ---------------------------------------------------------------------------
# Discovery factory wiring
# ---------------------------------------------------------------------------


def _clear_caches() -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    get_trend_discovery.cache_clear()
    from app.services.trends import get_trends_adapter

    get_trends_adapter.cache_clear()


def test_factory_defaults_to_curated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRENDS_DISCOVERY_SOURCE", raising=False)
    monkeypatch.delenv("TRENDS_PROVIDER", raising=False)
    _clear_caches()
    try:
        d = get_trend_discovery()
        assert isinstance(d, CuratedWatchlistDiscovery)
    finally:
        _clear_caches()


def test_factory_shopping_insight_mock_uses_mock_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRENDS_DISCOVERY_SOURCE", "shopping_insight")
    monkeypatch.setenv("TRENDS_PROVIDER", "mock")
    _clear_caches()
    try:
        d = get_trend_discovery()
        assert isinstance(d, NaverShoppingInsightDiscovery)
        # internal adapter is the deterministic mock so dev/CI never needs network
        assert isinstance(d._adapter, MockTrendsAdapter)  # type: ignore[attr-defined]
    finally:
        _clear_caches()


def test_factory_shopping_insight_live_requires_naver_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRENDS_DISCOVERY_SOURCE", "shopping_insight")
    monkeypatch.setenv("TRENDS_PROVIDER", "live")
    monkeypatch.delenv("NAVER_DATALAB_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_DATALAB_CLIENT_SECRET", raising=False)
    _clear_caches()
    try:
        with pytest.raises(TrendsAdapterError, match="NAVER_DATALAB_CLIENT_ID"):
            get_trend_discovery()
    finally:
        _clear_caches()


def test_factory_shopping_insight_live_returns_naver_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRENDS_DISCOVERY_SOURCE", "shopping_insight")
    monkeypatch.setenv("TRENDS_PROVIDER", "live")
    monkeypatch.setenv("NAVER_DATALAB_CLIENT_ID", "id")
    monkeypatch.setenv("NAVER_DATALAB_CLIENT_SECRET", "sec")
    monkeypatch.setenv("NAVER_SHOPPING_INSIGHT_CATEGORY_CODE", "50000006")
    _clear_caches()
    try:
        d = get_trend_discovery()
        assert isinstance(d, NaverShoppingInsightDiscovery)
        adapter = d._adapter  # type: ignore[attr-defined]
        assert isinstance(adapter, NaverShoppingInsightAdapter)
        assert adapter.category_code == "50000006"
    finally:
        _clear_caches()
