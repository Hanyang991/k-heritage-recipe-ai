"""Tests for ``MultiSourceDiscovery.discover_with_breakdown`` and
``app.services.trends.debug.build_debug_response``."""

from __future__ import annotations

from datetime import date

from app.services.trends import (
    CuratedWatchlistDiscovery,
    MultiSourceDiscovery,
    NaverShoppingInsightDiscovery,
    StaticCandidateProvider,
)
from app.services.trends.base import TrendDataPoint, TrendKeywordSeries
from app.services.trends.debug import build_debug_response
from app.services.trends.mock import MockTrendsAdapter
from app.services.trends.multi_source import MultiSourceBreakdown


class _FakeAdapter:
    def __init__(self, series: list[TrendKeywordSeries]) -> None:
        self._series = series

    def fetch_series(self, keywords, start, end, time_unit="week"):  # type: ignore[no-untyped-def]
        return [s for s in self._series if s.keyword in keywords]


class _FakeProvider:
    def __init__(self, name: str, keywords: list[str]) -> None:
        self.name = name
        self._keywords = keywords

    def discover_candidates(self, today=None, limit=50):  # type: ignore[no-untyped-def]
        return list(self._keywords)


class _ExplodingProvider:
    name = "exploding"

    def discover_candidates(self, today=None, limit=50):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated upstream 500")


def _series(keyword: str, points: list[tuple[date, float]]) -> TrendKeywordSeries:
    return TrendKeywordSeries(
        keyword=keyword,
        data=tuple(TrendDataPoint(period=d, ratio=r) for d, r in points),
    )


# ---------------------------------------------------------------------------
# MultiSourceDiscovery.discover_with_breakdown
# ---------------------------------------------------------------------------


def test_breakdown_per_provider_counts_and_sample() -> None:
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter(
        [
            _series("쑥라떼", [(week_a, 50.0), (week_b, 80.0)]),
            _series("김치라떼", [(week_a, 10.0), (week_b, 20.0)]),
            _series("두바이강정", [(week_a, 5.0), (week_b, 15.0)]),
        ]
    )
    d = MultiSourceDiscovery(
        adapter,
        [
            _FakeProvider("static", ["쑥라떼", "김치라떼"]),
            _FakeProvider("llm_expansion", ["두바이강정", "쑥라떼"]),  # one dupe
        ],
    )

    breakdown = d.discover_with_breakdown(today=week_b, limit=10)

    assert isinstance(breakdown, MultiSourceBreakdown)
    names = [r.name for r in breakdown.providers]
    assert names == ["static", "llm_expansion"]

    static_row = breakdown.providers[0]
    assert static_row.candidate_count == 2
    assert static_row.candidates_sample == ("쑥라떼", "김치라떼")
    assert static_row.error is None

    llm_row = breakdown.providers[1]
    assert llm_row.candidate_count == 2  # raw count from provider, no dedup
    assert llm_row.candidates_sample == ("두바이강정", "쑥라떼")
    assert llm_row.error is None


def test_breakdown_all_sources_attribution_includes_dupes() -> None:
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter([_series("쑥라떼", [(week_a, 50.0), (week_b, 80.0)])])
    d = MultiSourceDiscovery(
        adapter,
        [
            _FakeProvider("static", ["쑥라떼"]),
            _FakeProvider("google_trends_daily", ["쑥라떼"]),
            _FakeProvider("llm_expansion", ["쑥라떼"]),
        ],
    )

    breakdown = d.discover_with_breakdown(today=week_b, limit=10)

    # First-emitter wins for `source`; full set surfaces via keyword_sources.
    assert breakdown.ranked[0].source == "static"
    assert breakdown.keyword_sources["쑥라떼"] == (
        "static",
        "google_trends_daily",
        "llm_expansion",
    )


def test_breakdown_unique_and_scored_counts() -> None:
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter(
        [
            _series("a", [(week_a, 10.0), (week_b, 20.0)]),
            _series("b", [(week_a, 5.0), (week_b, 10.0)]),
            # "c" requested but adapter returns no series for it.
        ]
    )
    d = MultiSourceDiscovery(
        adapter,
        [_FakeProvider("static", ["a", "b", "c"])],
    )

    breakdown = d.discover_with_breakdown(today=week_b, limit=10)

    assert breakdown.unique_candidate_count == 3
    assert breakdown.scored_count == 2


def test_breakdown_captures_provider_error_text() -> None:
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter([_series("쑥라떼", [(week_a, 50.0), (week_b, 80.0)])])
    d = MultiSourceDiscovery(
        adapter,
        [_FakeProvider("static", ["쑥라떼"]), _ExplodingProvider()],
    )

    breakdown = d.discover_with_breakdown(today=week_b, limit=10)

    exploding_row = next(r for r in breakdown.providers if r.name == "exploding")
    assert exploding_row.candidate_count == 0
    assert exploding_row.candidates_sample == ()
    assert exploding_row.error is not None
    assert "RuntimeError" in exploding_row.error
    assert "simulated upstream 500" in exploding_row.error
    # The exploding provider doesn't break the surviving provider.
    static_row = next(r for r in breakdown.providers if r.name == "static")
    assert static_row.error is None
    assert breakdown.ranked[0].keyword == "쑥라떼"


def test_breakdown_records_per_provider_elapsed_ms_non_negative() -> None:
    week_b = date(2025, 5, 12)
    adapter = _FakeAdapter([])
    d = MultiSourceDiscovery(
        adapter,
        [_FakeProvider("static", []), _FakeProvider("llm_expansion", [])],
    )
    breakdown = d.discover_with_breakdown(today=week_b, limit=10)
    for row in breakdown.providers:
        assert row.elapsed_ms >= 0


def test_breakdown_returns_empty_envelope_when_all_providers_empty() -> None:
    week_b = date(2025, 5, 12)
    adapter = _FakeAdapter([])
    d = MultiSourceDiscovery(
        adapter,
        [_FakeProvider("static", []), _FakeProvider("llm_expansion", [])],
    )

    breakdown = d.discover_with_breakdown(today=week_b, limit=10)

    assert breakdown.unique_candidate_count == 0
    assert breakdown.scored_count == 0
    assert breakdown.ranked == ()
    assert breakdown.keyword_sources == {}
    # Per-provider rows still present (admin can see "all providers returned 0").
    assert [r.name for r in breakdown.providers] == ["static", "llm_expansion"]


def test_breakdown_respects_sample_size_clamp() -> None:
    week_b = date(2025, 5, 12)
    adapter = _FakeAdapter([])
    big = [f"kw-{i}" for i in range(50)]
    d = MultiSourceDiscovery(adapter, [_FakeProvider("static", big)])
    breakdown = d.discover_with_breakdown(today=week_b, limit=10, sample_size=5)
    assert breakdown.providers[0].candidate_count == 50
    assert len(breakdown.providers[0].candidates_sample) == 5
    assert breakdown.providers[0].candidates_sample == tuple(big[:5])


def test_discover_still_returns_ranked_list_only() -> None:
    """Existing ``discover`` shape must not change after the breakdown refactor."""
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter([_series("쑥라떼", [(week_a, 50.0), (week_b, 80.0)])])
    d = MultiSourceDiscovery(adapter, [_FakeProvider("static", ["쑥라떼"])])
    result = d.discover(today=week_b, limit=10)
    assert isinstance(result, list)
    assert result[0].keyword == "쑥라떼"
    assert result[0].source == "static"


# ---------------------------------------------------------------------------
# build_debug_response
# ---------------------------------------------------------------------------


def test_build_debug_response_for_multi_source() -> None:
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter(
        [
            _series("쑥라떼", [(week_a, 50.0), (week_b, 80.0)]),
            _series("두바이강정", [(week_a, 5.0), (week_b, 15.0)]),
        ]
    )
    d = MultiSourceDiscovery(
        adapter,
        [
            _FakeProvider("static", ["쑥라떼"]),
            _FakeProvider("llm_expansion", ["두바이강정", "쑥라떼"]),
        ],
    )

    response = build_debug_response(d, today=week_b, limit=10)

    assert response.discovery_type == "multi_source"
    assert response.ref_date == week_b
    assert response.limit == 10
    assert response.unique_candidate_count == 2
    assert response.scored_count == 2
    provider_names = [p.name for p in response.providers]
    assert provider_names == ["static", "llm_expansion"]
    # Keywords ranked highest-score first; 쑥라떼 emitted by both sources.
    suk = next(r for r in response.ranked if r.keyword == "쑥라떼")
    assert suk.primary_source == "static"
    assert suk.all_sources == ["static", "llm_expansion"]
    dubai = next(r for r in response.ranked if r.keyword == "두바이강정")
    assert dubai.all_sources == ["llm_expansion"]


def test_build_debug_response_for_curated() -> None:
    """Single-source discoveries synthesize one provider row."""
    adapter = MockTrendsAdapter()
    d = CuratedWatchlistDiscovery(adapter, candidates=["쑥라떼", "흑임자라떼"])

    response = build_debug_response(d, today=date(2025, 5, 12), limit=5)

    assert response.discovery_type == "curated"
    assert len(response.providers) == 1
    only = response.providers[0]
    assert only.name == "curated_watchlist"
    assert only.candidate_count == 2  # from CuratedWatchlistDiscovery.candidates
    assert only.error is None
    # Ranked rows use the ranked keyword's source as the single source.
    for row in response.ranked:
        assert row.all_sources == [row.primary_source]
    assert response.unique_candidate_count == 2


def test_build_debug_response_for_shopping_insight() -> None:
    """Shopping insight discovery names itself ``naver_shopping_insight``."""
    adapter = MockTrendsAdapter()
    d = NaverShoppingInsightDiscovery(adapter, candidates=["쑥라떼"])

    response = build_debug_response(d, today=date(2025, 5, 12), limit=5)

    assert response.discovery_type == d.name
    assert len(response.providers) == 1
    assert response.providers[0].name == "naver_shopping_insight"


def test_build_debug_response_defaults_today_to_date_today() -> None:
    adapter = MockTrendsAdapter()
    d = MultiSourceDiscovery(adapter, [StaticCandidateProvider(["쑥라떼"])])
    response = build_debug_response(d, limit=5)
    assert response.ref_date == date.today()
