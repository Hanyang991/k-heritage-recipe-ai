"""Tests for ``MultiSourceDiscovery``."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.trends import (
    CuratedWatchlistDiscovery,
    GoogleTrendsCandidateProvider,
    LLMExpansionCandidateProvider,
    MultiSourceDiscovery,
    NaverNewsCandidateProvider,
    NaverShoppingInsightDiscovery,
    StaticCandidateProvider,
    get_trend_discovery,
)
from app.services.trends.base import TrendDataPoint, TrendKeywordSeries
from app.services.trends.mock import MockTrendsAdapter


class _FakeAdapter:
    def __init__(self, series: list[TrendKeywordSeries]) -> None:
        self._series = series
        self.calls: list[tuple[list[str], date, date, str]] = []

    def fetch_series(self, keywords, start, end, time_unit="week"):  # type: ignore[no-untyped-def]
        self.calls.append((list(keywords), start, end, time_unit))
        # Return only series for keywords that were requested
        return [s for s in self._series if s.keyword in keywords]


class _FakeProvider:
    def __init__(self, name: str, keywords: list[str]) -> None:
        self.name = name
        self._keywords = keywords
        self.call_count = 0

    def discover_candidates(self, today=None, limit=50):  # type: ignore[no-untyped-def]
        self.call_count += 1
        return list(self._keywords)


class _ExplodingProvider:
    name = "exploding"

    def discover_candidates(self, today=None, limit=50):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated provider failure")


def _series(keyword: str, points: list[tuple[date, float]]) -> TrendKeywordSeries:
    return TrendKeywordSeries(
        keyword=keyword,
        data=tuple(TrendDataPoint(period=d, ratio=r) for d, r in points),
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_requires_at_least_one_provider() -> None:
    with pytest.raises(ValueError, match="at least one provider"):
        MultiSourceDiscovery(_FakeAdapter([]), [])


def test_name_is_multi_source() -> None:
    discovery = MultiSourceDiscovery(_FakeAdapter([]), [StaticCandidateProvider(["a"])])
    assert discovery.name == "multi_source"


# ---------------------------------------------------------------------------
# Candidate aggregation
# ---------------------------------------------------------------------------


def test_merges_candidates_from_multiple_providers() -> None:
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter(
        [
            _series("쑥라떼", [(week_a, 50.0), (week_b, 80.0)]),
            _series("김치라떼", [(week_a, 10.0), (week_b, 20.0)]),
        ]
    )
    discovery = MultiSourceDiscovery(
        adapter,
        [
            _FakeProvider("static", ["쑥라떼"]),
            _FakeProvider("google_trends_daily", ["김치라떼"]),
        ],
    )

    result = discovery.discover(today=week_b, limit=10)
    keywords = [r.keyword for r in result]
    assert "쑥라떼" in keywords
    assert "김치라떼" in keywords


def test_dedupes_across_providers_preserving_first_attribution() -> None:
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter([_series("쑥라떼", [(week_a, 50.0), (week_b, 80.0)])])
    discovery = MultiSourceDiscovery(
        adapter,
        [
            _FakeProvider("static", ["쑥라떼"]),
            _FakeProvider("google_trends_daily", ["쑥라떼"]),  # also emits it
        ],
    )

    result = discovery.discover(today=week_b, limit=10)
    assert len(result) == 1
    assert result[0].keyword == "쑥라떼"
    assert result[0].source == "static", "first provider wins attribution"


def test_attribution_reflects_emitting_provider() -> None:
    """If only google emits the keyword, source = google_trends_daily."""
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter(
        [
            _series("쑥라떼", [(week_a, 50.0), (week_b, 80.0)]),
            _series("김치라떼", [(week_a, 10.0), (week_b, 20.0)]),
        ]
    )
    discovery = MultiSourceDiscovery(
        adapter,
        [
            _FakeProvider("static", ["쑥라떼"]),
            _FakeProvider("google_trends_daily", ["김치라떼"]),
        ],
    )

    result = discovery.discover(today=week_b, limit=10)
    by_keyword = {r.keyword: r for r in result}
    assert by_keyword["쑥라떼"].source == "static"
    assert by_keyword["김치라떼"].source == "google_trends_daily"


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


def test_provider_failure_is_isolated() -> None:
    """One failing provider doesn't break the rest."""
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter([_series("쑥라떼", [(week_a, 50.0), (week_b, 80.0)])])
    healthy = _FakeProvider("static", ["쑥라떼"])
    discovery = MultiSourceDiscovery(adapter, [_ExplodingProvider(), healthy])

    result = discovery.discover(today=week_b, limit=10)
    assert [r.keyword for r in result] == ["쑥라떼"]
    assert healthy.call_count == 1


def test_returns_empty_when_no_candidates() -> None:
    discovery = MultiSourceDiscovery(_FakeAdapter([]), [_FakeProvider("empty", [])])
    assert discovery.discover() == []


# ---------------------------------------------------------------------------
# Ranking — same blended score as CuratedWatchlistDiscovery
# ---------------------------------------------------------------------------


def test_ranking_matches_blended_score_formula() -> None:
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter(
        [
            _series("쑥라떼", [(week_a, 50.0), (week_b, 80.0)]),  # 0.4*80 + 0.6*60   = 68
            _series("대추차", [(week_a, 90.0), (week_b, 60.0)]),  # 0.4*60 + 0.6*-33.33 = ~4
            _series("수정과", [(week_a, 30.0), (week_b, 30.0)]),  # 0.4*30 + 0.6*0   = 12
        ]
    )
    discovery = MultiSourceDiscovery(
        adapter,
        [_FakeProvider("static", ["쑥라떼", "대추차", "수정과"])],
    )

    result = discovery.discover(today=week_b, limit=10)
    assert [r.keyword for r in result] == ["쑥라떼", "수정과", "대추차"]
    assert result[0].score == pytest.approx(68.0)


def test_caps_at_limit() -> None:
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter(
        [_series(f"kw{i}", [(week_a, float(i + 1)), (week_b, float(i + 2))]) for i in range(10)]
    )
    discovery = MultiSourceDiscovery(
        adapter,
        [_FakeProvider("static", [f"kw{i}" for i in range(10)])],
    )
    assert len(discovery.discover(today=week_b, limit=3)) == 3


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------


def _clear_caches() -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    get_trend_discovery.cache_clear()
    from app.services.trends import get_trends_adapter

    get_trends_adapter.cache_clear()


def test_factory_open_returns_multi_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRENDS_DISCOVERY_SOURCE", "open")
    _clear_caches()
    try:
        d = get_trend_discovery()
        assert isinstance(d, MultiSourceDiscovery)
        provider_names = [p.name for p in d.providers]
        assert "static" in provider_names
        assert "google_trends_daily" in provider_names
        assert "naver_news" in provider_names
    finally:
        _clear_caches()


def test_factory_open_can_disable_google(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRENDS_DISCOVERY_SOURCE", "open")
    monkeypatch.setenv("TRENDS_OPEN_GOOGLE_ENABLED", "false")
    _clear_caches()
    try:
        d = get_trend_discovery()
        assert isinstance(d, MultiSourceDiscovery)
        provider_names = [p.name for p in d.providers]
        assert provider_names == ["static", "naver_news"]
    finally:
        _clear_caches()


def test_factory_open_can_disable_naver_news(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRENDS_DISCOVERY_SOURCE", "open")
    monkeypatch.setenv("TRENDS_OPEN_NAVER_NEWS_ENABLED", "false")
    _clear_caches()
    try:
        d = get_trend_discovery()
        assert isinstance(d, MultiSourceDiscovery)
        provider_names = [p.name for p in d.providers]
        assert "naver_news" not in provider_names
        assert "static" in provider_names
        assert "google_trends_daily" in provider_names
    finally:
        _clear_caches()


def test_factory_open_can_disable_both_open_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRENDS_DISCOVERY_SOURCE", "open")
    monkeypatch.setenv("TRENDS_OPEN_GOOGLE_ENABLED", "false")
    monkeypatch.setenv("TRENDS_OPEN_NAVER_NEWS_ENABLED", "false")
    _clear_caches()
    try:
        d = get_trend_discovery()
        assert isinstance(d, MultiSourceDiscovery)
        provider_names = [p.name for p in d.providers]
        assert provider_names == ["static"]
    finally:
        _clear_caches()


def test_factory_open_llm_provider_off_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM costs money, so it's opt-in even when ``TRENDS_DISCOVERY_SOURCE=open``."""
    monkeypatch.setenv("TRENDS_DISCOVERY_SOURCE", "open")
    monkeypatch.delenv("TRENDS_OPEN_LLM_ENABLED", raising=False)
    _clear_caches()
    try:
        d = get_trend_discovery()
        assert isinstance(d, MultiSourceDiscovery)
        provider_names = [p.name for p in d.providers]
        assert "llm_expansion" not in provider_names
    finally:
        _clear_caches()


def test_factory_open_with_llm_enabled_wires_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRENDS_DISCOVERY_SOURCE", "open")
    monkeypatch.setenv("TRENDS_OPEN_LLM_ENABLED", "true")
    _clear_caches()
    try:
        d = get_trend_discovery()
        assert isinstance(d, MultiSourceDiscovery)
        provider_names = [p.name for p in d.providers]
        assert "llm_expansion" in provider_names
    finally:
        _clear_caches()


def test_factory_open_uses_underlying_adapter_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Open discovery rides the same TRENDS_PROVIDER toggle for series data."""
    monkeypatch.setenv("TRENDS_DISCOVERY_SOURCE", "open")
    monkeypatch.setenv("TRENDS_PROVIDER", "mock")
    monkeypatch.setenv("TRENDS_OPEN_GOOGLE_ENABLED", "false")  # avoid live HTTP
    _clear_caches()
    try:
        d = get_trend_discovery()
        assert isinstance(d, MultiSourceDiscovery)
        assert isinstance(d._adapter, MockTrendsAdapter)  # type: ignore[attr-defined]
    finally:
        _clear_caches()


def test_factory_default_still_curated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adding ``open`` doesn't break the default ``curated`` source."""
    monkeypatch.delenv("TRENDS_DISCOVERY_SOURCE", raising=False)
    _clear_caches()
    try:
        d = get_trend_discovery()
        assert isinstance(d, CuratedWatchlistDiscovery)
        assert not isinstance(d, NaverShoppingInsightDiscovery)
        assert not isinstance(d, MultiSourceDiscovery)
    finally:
        _clear_caches()


def test_factory_google_trends_provider_construction_respects_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRENDS_DISCOVERY_SOURCE", "open")
    monkeypatch.setenv("GOOGLE_TRENDS_GEO", "US")
    monkeypatch.setenv("GOOGLE_TRENDS_HL", "en-US")
    _clear_caches()
    try:
        d = get_trend_discovery()
        assert isinstance(d, MultiSourceDiscovery)
        google = next(
            (p for p in d.providers if isinstance(p, GoogleTrendsCandidateProvider)),
            None,
        )
        assert google is not None
        assert google._geo == "US"  # type: ignore[attr-defined]
        assert google._hl == "en-US"  # type: ignore[attr-defined]
    finally:
        _clear_caches()


def test_factory_naver_news_provider_construction_respects_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRENDS_DISCOVERY_SOURCE", "open")
    monkeypatch.setenv("NAVER_DATALAB_CLIENT_ID", "id-123")
    monkeypatch.setenv("NAVER_DATALAB_CLIENT_SECRET", "secret-456")
    monkeypatch.setenv("NAVER_NEWS_SEED_QUERIES", "호떡 트렌드, 한과 신상,")
    monkeypatch.setenv("NAVER_NEWS_DISPLAY_PER_QUERY", "77")
    _clear_caches()
    try:
        d = get_trend_discovery()
        assert isinstance(d, MultiSourceDiscovery)
        naver = next(
            (p for p in d.providers if isinstance(p, NaverNewsCandidateProvider)),
            None,
        )
        assert naver is not None
        assert naver._client_id == "id-123"  # type: ignore[attr-defined]
        assert naver._client_secret == "secret-456"  # type: ignore[attr-defined]
        # Empty seed-query entries are stripped, whitespace trimmed.
        assert naver._seed_queries == ("호떡 트렌드", "한과 신상")  # type: ignore[attr-defined]
        assert naver._display_per_query == 77  # type: ignore[attr-defined]
    finally:
        _clear_caches()


def test_factory_naver_news_seed_queries_fall_back_to_defaults_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.trends.naver_news import DEFAULT_SEED_QUERIES

    monkeypatch.setenv("TRENDS_DISCOVERY_SOURCE", "open")
    monkeypatch.setenv("NAVER_NEWS_SEED_QUERIES", "   ,,,  ")
    _clear_caches()
    try:
        d = get_trend_discovery()
        assert isinstance(d, MultiSourceDiscovery)
        naver = next(
            (p for p in d.providers if isinstance(p, NaverNewsCandidateProvider)),
            None,
        )
        assert naver is not None
        assert naver._seed_queries == DEFAULT_SEED_QUERIES  # type: ignore[attr-defined]
    finally:
        _clear_caches()


def test_factory_llm_provider_construction_respects_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRENDS_DISCOVERY_SOURCE", "open")
    monkeypatch.setenv("TRENDS_OPEN_LLM_ENABLED", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("GEMINI_TRENDS_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("GEMINI_TRENDS_TARGET_COUNT", "42")
    monkeypatch.setenv("GEMINI_TRENDS_BASE_URL", "https://example.test/gemini")
    _clear_caches()
    try:
        d = get_trend_discovery()
        assert isinstance(d, MultiSourceDiscovery)
        llm = next(
            (p for p in d.providers if isinstance(p, LLMExpansionCandidateProvider)),
            None,
        )
        assert llm is not None
        assert llm._api_key == "gemini-test-key"  # type: ignore[attr-defined]
        assert llm._model == "gemini-2.5-pro"  # type: ignore[attr-defined]
        assert llm._target_count == 42  # type: ignore[attr-defined]
        assert llm._base_url == "https://example.test/gemini"  # type: ignore[attr-defined]
    finally:
        _clear_caches()
