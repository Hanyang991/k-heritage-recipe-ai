"""Unit tests for the trends adapter abstraction (mock + Naver DataLab)."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.trends import (
    TrendsAdapterError,
    get_trends_adapter,
)
from app.services.trends.mock import MockTrendsAdapter
from app.services.trends.naver import NaverDatalabAdapter, _chunk, _parse_response

# ---------------------------------------------------------------------------
# Mock adapter
# ---------------------------------------------------------------------------


def test_mock_adapter_returns_one_series_per_keyword() -> None:
    adapter = MockTrendsAdapter()
    series = adapter.fetch_series(
        ["쑥라떼", "오미자에이드"],
        start=date(2025, 1, 1),
        end=date(2025, 1, 29),
        time_unit="week",
    )
    assert len(series) == 2
    assert {s.keyword for s in series} == {"쑥라떼", "오미자에이드"}
    # 5 weekly points across a 4-week range (start, +7, +14, +21, +28)
    assert all(len(s.data) == 5 for s in series)


def test_mock_adapter_is_deterministic() -> None:
    a = MockTrendsAdapter()
    b = MockTrendsAdapter()
    args = (["쑥라떼"], date(2025, 1, 1), date(2025, 1, 29), "week")
    assert a.fetch_series(*args) == b.fetch_series(*args)


def test_mock_adapter_empty_keywords_returns_empty() -> None:
    assert MockTrendsAdapter().fetch_series([], date(2025, 1, 1), date(2025, 1, 31)) == []


def test_mock_adapter_ratios_stay_in_0_100_range() -> None:
    series = MockTrendsAdapter().fetch_series(
        ["가", "나", "다", "라"], date(2025, 1, 1), date(2025, 6, 1), "week"
    )
    for s in series:
        for p in s.data:
            assert 0.0 <= p.ratio <= 100.0


# ---------------------------------------------------------------------------
# Naver adapter — chunking + parsing
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
                "keywords": ["쑥라떼"],
                "data": [
                    {"period": "2025-02-24", "ratio": 86.00823},
                    {"period": "2025-03-03", "ratio": 82.71604},
                ],
            },
        ]
    }
    series = _parse_response(payload)
    assert len(series) == 1
    assert series[0].keyword == "쑥라떼"
    assert series[0].data[0].period == date(2025, 2, 24)
    assert series[0].data[0].ratio == pytest.approx(86.00823)


def test_parse_response_skips_malformed_rows() -> None:
    payload: dict[str, Any] = {
        "results": [
            {
                "title": "x",
                "data": [
                    {"period": "2025-01-01", "ratio": 10},
                    {"period": "not-a-date", "ratio": 99},  # skipped
                    {"period": "2025-01-08"},  # ratio missing — skipped
                    {"period": "2025-01-15", "ratio": 20},
                ],
            }
        ]
    }
    series = _parse_response(payload)
    assert [p.period for p in series[0].data] == [date(2025, 1, 1), date(2025, 1, 15)]


# ---------------------------------------------------------------------------
# Naver adapter — HTTP layer (mocked httpx)
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, json_body: dict[str, Any] | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = "" if json_body is None else str(json_body)
    return resp


def test_naver_adapter_chunks_into_multiple_requests() -> None:
    adapter = NaverDatalabAdapter(client_id="id", client_secret="sec")
    keywords = [f"k{i}" for i in range(12)]  # → 3 chunks: 5 / 5 / 2

    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, {"results": []})
        adapter.fetch_series(keywords, date(2025, 1, 1), date(2025, 1, 31))
        assert post.call_count == 3
        # First call carries the first 5 keywords, each in its own group
        first_body = post.call_args_list[0].kwargs["json"]
        assert [g["groupName"] for g in first_body["keywordGroups"]] == keywords[:5]


def test_naver_adapter_sends_auth_headers() -> None:
    adapter = NaverDatalabAdapter(client_id="my-id", client_secret="my-secret")
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, {"results": []})
        adapter.fetch_series(["a"], date(2025, 1, 1), date(2025, 1, 31))
        headers = post.call_args.kwargs["headers"]
        assert headers["X-Naver-Client-Id"] == "my-id"
        assert headers["X-Naver-Client-Secret"] == "my-secret"


def test_naver_adapter_raises_on_401() -> None:
    adapter = NaverDatalabAdapter(client_id="bad", client_secret="bad")
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(401, {"errorMessage": "Unauthorized"})
        with pytest.raises(TrendsAdapterError, match="401"):
            adapter.fetch_series(["a"], date(2025, 1, 1), date(2025, 1, 31))


def test_naver_adapter_raises_on_429() -> None:
    adapter = NaverDatalabAdapter(client_id="id", client_secret="sec")
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(429, {"errorMessage": "Quota"})
        with pytest.raises(TrendsAdapterError, match="429"):
            adapter.fetch_series(["a"], date(2025, 1, 1), date(2025, 1, 31))


def test_naver_adapter_wraps_transport_errors() -> None:
    adapter = NaverDatalabAdapter(client_id="id", client_secret="sec")
    with patch("httpx.Client.post", side_effect=httpx.ConnectError("boom")):
        with pytest.raises(TrendsAdapterError, match="Naver DataLab request failed"):
            adapter.fetch_series(["a"], date(2025, 1, 1), date(2025, 1, 31))


def test_naver_adapter_returns_parsed_series() -> None:
    adapter = NaverDatalabAdapter(client_id="id", client_secret="sec")
    payload = {
        "results": [
            {
                "title": "쑥라떼",
                "data": [
                    {"period": "2025-02-24", "ratio": 86.0},
                    {"period": "2025-03-03", "ratio": 82.7},
                ],
            }
        ]
    }
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, payload)
        series = adapter.fetch_series(["쑥라떼"], date(2025, 2, 24), date(2025, 3, 3))
    assert len(series) == 1
    assert series[0].keyword == "쑥라떼"
    assert len(series[0].data) == 2


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_defaults_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRENDS_PROVIDER", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    get_trends_adapter.cache_clear()
    try:
        assert isinstance(get_trends_adapter(), MockTrendsAdapter)
    finally:
        get_settings.cache_clear()
        get_trends_adapter.cache_clear()


def test_factory_live_requires_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRENDS_PROVIDER", "live")
    monkeypatch.delenv("NAVER_DATALAB_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_DATALAB_CLIENT_SECRET", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    get_trends_adapter.cache_clear()
    try:
        with pytest.raises(TrendsAdapterError, match="NAVER_DATALAB_CLIENT_ID"):
            get_trends_adapter()
    finally:
        get_settings.cache_clear()
        get_trends_adapter.cache_clear()


def test_factory_live_returns_naver_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRENDS_PROVIDER", "live")
    monkeypatch.setenv("NAVER_DATALAB_CLIENT_ID", "id")
    monkeypatch.setenv("NAVER_DATALAB_CLIENT_SECRET", "sec")
    from app.config import get_settings

    get_settings.cache_clear()
    get_trends_adapter.cache_clear()
    try:
        adapter = get_trends_adapter()
        assert isinstance(adapter, NaverDatalabAdapter)
    finally:
        get_settings.cache_clear()
        get_trends_adapter.cache_clear()
