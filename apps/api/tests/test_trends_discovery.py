"""Unit tests for ``CuratedWatchlistDiscovery``."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.trends.base import TrendDataPoint, TrendKeywordSeries
from app.services.trends.discovery import CuratedWatchlistDiscovery, DiscoveredKeyword


class _FakeAdapter:
    """Deterministic in-memory adapter."""

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


def test_discovery_ranks_by_blended_popular_plus_rise() -> None:
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter(
        [
            # popular & rising — should win
            _series("쑥라떼", [(week_a, 50.0), (week_b, 80.0)]),
            # popular but falling — score drops because rise is negative
            _series("대추차", [(week_a, 90.0), (week_b, 60.0)]),
            # small but stable
            _series("수정과", [(week_a, 30.0), (week_b, 30.0)]),
        ]
    )
    discovery = CuratedWatchlistDiscovery(adapter, ["쑥라떼", "대추차", "수정과"], weeks=4)

    result = discovery.discover(today=week_b, limit=10)

    # Blended score with defaults (0.4 * current + 0.6 * rise_pct):
    #   쑥라떼: 0.4*80 + 0.6*60.0   = 32 + 36   = 68.0
    #   대추차: 0.4*60 + 0.6*-33.33 = 24 - 20.0 = 4.0
    #   수정과: 0.4*30 + 0.6*0      = 12.0
    # So: 쑥라떼 > 수정과 > 대추차 — falling keyword loses to stable one.
    assert [d.keyword for d in result] == ["쑥라떼", "수정과", "대추차"]
    assert result[0].score == pytest.approx(68.0, abs=0.01)
    assert result[0].current_ratio == pytest.approx(80.0)
    assert result[0].rise_percent == pytest.approx(60.0, abs=0.01)
    assert result[0].source == "curated"
    # Adapter is called once with the full candidate pool.
    assert adapter.calls[0][0] == ["쑥라떼", "대추차", "수정과"]


def test_discovery_clamps_extreme_rise_so_small_bases_dont_dominate() -> None:
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter(
        [
            # +900% rise but tiny absolute value — clamped at +200%
            _series("틈새키워드", [(week_a, 0.5), (week_b, 5.0)]),
            # stable mega-popular
            _series("쑥라떼", [(week_a, 80.0), (week_b, 80.0)]),
        ]
    )
    discovery = CuratedWatchlistDiscovery(adapter, ["틈새키워드", "쑥라떼"])

    result = discovery.discover(today=week_b, limit=10)
    # 틈새키워드: 0.4*5 + 0.6*200(clamped) = 2 + 120 = 122
    # 쑥라떼:   0.4*80 + 0.6*0           = 32
    # With clamp at 200, the spiking keyword still wins — that's intended
    # ("급상승" surfaces newcomers). Test pins the clamp boundary so we
    # notice if it gets accidentally widened.
    assert [d.keyword for d in result] == ["틈새키워드", "쑥라떼"]
    assert result[0].score == pytest.approx(0.4 * 5.0 + 0.6 * 200.0, abs=0.01)


def test_discovery_ignores_empty_series_and_caps_to_limit() -> None:
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter(
        [
            _series("a", []),
            _series("b", [(week_b, 10.0)]),
            _series("c", [(week_a, 20.0), (week_b, 30.0)]),
            _series("d", [(week_a, 5.0), (week_b, 50.0)]),
        ]
    )
    discovery = CuratedWatchlistDiscovery(adapter, ["a", "b", "c", "d"])
    result = discovery.discover(today=week_b, limit=2)
    assert len(result) == 2
    assert all(isinstance(d, DiscoveredKeyword) for d in result)
    # "a" has no points → excluded; "b" has one point → rise=0; "d" rose 900% (clamped)
    assert result[0].keyword == "d"


def test_discovery_single_point_treats_rise_as_zero() -> None:
    week = date(2025, 5, 12)
    adapter = _FakeAdapter([_series("쑥라떼", [(week, 40.0)])])
    discovery = CuratedWatchlistDiscovery(adapter, ["쑥라떼"])
    [d] = discovery.discover(today=week, limit=5)
    assert d.rise_percent == pytest.approx(0.0)
    assert d.current_ratio == pytest.approx(40.0)
    # 0.4 * 40 + 0.6 * 0 = 16
    assert d.score == pytest.approx(16.0)
