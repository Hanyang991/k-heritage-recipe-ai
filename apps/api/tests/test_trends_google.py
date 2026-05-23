"""Tests for ``GoogleTrendsCandidateProvider``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from app.services.trends.google_trends import (
    GoogleTrendsCandidateProvider,
    _parse_daily_trends_rss,
)


def _mock_response(status: int, body: str) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.text = body
    return resp


def _rss(queries: list[str]) -> str:
    items = "".join(
        f"<item><title>{q}</title><ht:approx_traffic>100+</ht:approx_traffic></item>"
        for q in queries
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<rss xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:ht="https://trends.google.com/trending/rss" version="2.0">
<channel>
<title>Daily Search Trends</title>
{items}
</channel>
</rss>"""


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_pulls_titles_from_rss() -> None:
    assert _parse_daily_trends_rss(_rss(["쑥라떼", "BTS 컴백"])) == ["쑥라떼", "BTS 컴백"]


def test_parse_returns_empty_on_invalid_xml() -> None:
    assert _parse_daily_trends_rss("not xml at all") == []


def test_parse_returns_empty_on_empty_feed() -> None:
    assert _parse_daily_trends_rss(_rss([])) == []


def test_parse_skips_items_without_title() -> None:
    body = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>good</title></item>
<item></item>
<item><title></title></item>
<item><title>   </title></item>
<item><title>also good</title></item>
</channel></rss>"""
    assert _parse_daily_trends_rss(body) == ["good", "also good"]


def test_parse_strips_title_whitespace() -> None:
    body = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>
   쑥라떼
</title></item>
</channel></rss>"""
    assert _parse_daily_trends_rss(body) == ["쑥라떼"]


# ---------------------------------------------------------------------------
# Provider behaviour
# ---------------------------------------------------------------------------


def test_provider_name() -> None:
    assert GoogleTrendsCandidateProvider().name == "google_trends_daily"


def test_provider_filters_to_food_keywords() -> None:
    raw = ["BTS 컴백", "쑥라떼", "윤석열 발언", "흑임자빙수", "테슬라 자동차"]
    provider = GoogleTrendsCandidateProvider()
    with patch("httpx.Client.get") as get:
        get.return_value = _mock_response(200, _rss(raw))
        out = provider.discover_candidates()
    assert out == ["쑥라떼", "흑임자빙수"]


def test_provider_dedupes_repeated_keywords() -> None:
    raw = ["쑥라떼", "쑥라떼", "흑임자빙수", "쑥라떼"]
    provider = GoogleTrendsCandidateProvider()
    with patch("httpx.Client.get") as get:
        get.return_value = _mock_response(200, _rss(raw))
        out = provider.discover_candidates()
    assert out == ["쑥라떼", "흑임자빙수"]


def test_provider_respects_limit() -> None:
    raw = ["쑥라떼", "흑임자빙수", "유자에이드", "오미자차"]
    provider = GoogleTrendsCandidateProvider()
    with patch("httpx.Client.get") as get:
        get.return_value = _mock_response(200, _rss(raw))
        out = provider.discover_candidates(limit=2)
    assert out == ["쑥라떼", "흑임자빙수"]


def test_provider_returns_empty_on_http_error() -> None:
    """Open-discovery providers must never crash the refresh job."""
    provider = GoogleTrendsCandidateProvider()
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("boom")):
        assert provider.discover_candidates() == []


def test_provider_returns_empty_on_non_200() -> None:
    provider = GoogleTrendsCandidateProvider()
    with patch("httpx.Client.get") as get:
        get.return_value = _mock_response(429, "rate limited")
        assert provider.discover_candidates() == []


def test_provider_returns_empty_on_invalid_body() -> None:
    provider = GoogleTrendsCandidateProvider()
    with patch("httpx.Client.get") as get:
        get.return_value = _mock_response(200, "not xml at all")
        assert provider.discover_candidates() == []


def test_provider_sends_geo_query_param() -> None:
    provider = GoogleTrendsCandidateProvider(geo="KR")
    with patch("httpx.Client.get") as get:
        get.return_value = _mock_response(200, _rss([]))
        provider.discover_candidates()
        assert get.call_args.kwargs["params"] == {"geo": "KR"}


def test_provider_returns_empty_when_no_food_candidates() -> None:
    raw = ["BTS 컴백", "윤석열 발언", "삼성전자 주가"]
    provider = GoogleTrendsCandidateProvider()
    with patch("httpx.Client.get") as get:
        get.return_value = _mock_response(200, _rss(raw))
        assert provider.discover_candidates() == []
