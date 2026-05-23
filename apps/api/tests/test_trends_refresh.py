"""Unit tests for the ``refresh_trends`` collection job."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.jobs.refresh_trends import refresh_trends
from app.models.trend import Trend
from app.services.trends.base import (
    TrendDataPoint,
    TrendKeywordSeries,
)


class _FakeAdapter:
    """Deterministic in-memory adapter for testing the refresh job in isolation."""

    def __init__(self, series: list[TrendKeywordSeries]) -> None:
        self._series = series

    def fetch_series(self, keywords, start, end, time_unit="week") -> list[TrendKeywordSeries]:  # type: ignore[no-untyped-def]
        return list(self._series)


def _series(keyword: str, points: list[tuple[date, float]]) -> TrendKeywordSeries:
    return TrendKeywordSeries(
        keyword=keyword,
        data=tuple(TrendDataPoint(period=d, ratio=r) for d, r in points),
    )


def test_refresh_inserts_one_row_per_keyword(db_session: Session) -> None:
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter(
        [
            _series("쑥라떼", [(week_a, 50.0), (week_b, 80.0)]),
            _series("대추차", [(week_a, 90.0), (week_b, 60.0)]),
            _series("수정과", [(week_a, 30.0), (week_b, 30.0)]),
        ]
    )

    result = refresh_trends(
        db_session,
        watchlist=["쑥라떼", "대추차", "수정과"],
        adapter=adapter,
        today=week_b,
    )

    assert result.week_of == week_b
    assert result.inserted == 3
    assert result.updated == 0
    rows = db_session.query(Trend).order_by(Trend.rank.asc()).all()
    # Ranked by blended popularity + rise score, so 대추차 (falling) loses
    # to 수정과 (stable) even though 대추차 has higher absolute ratio.
    assert [r.keyword for r in rows] == ["쑥라떼", "수정과", "대추차"]
    assert [r.rank for r in rows] == [1, 2, 3]

    sukra = next(r for r in rows if r.keyword == "쑥라떼")
    assert sukra.change_percent == pytest.approx(60.0, abs=0.01)
    assert sukra.is_up is True

    daechu = next(r for r in rows if r.keyword == "대추차")
    assert daechu.change_percent == pytest.approx(-33.33, abs=0.01)
    assert daechu.is_up is False

    sujeong = next(r for r in rows if r.keyword == "수정과")
    assert sujeong.change_percent == pytest.approx(0.0)
    assert sujeong.is_up is True


def test_refresh_is_idempotent_on_same_week(db_session: Session) -> None:
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    adapter = _FakeAdapter(
        [
            _series("쑥라떼", [(week_a, 50.0), (week_b, 80.0)]),
            _series("대추차", [(week_a, 90.0), (week_b, 60.0)]),
        ]
    )
    refresh_trends(
        db_session,
        watchlist=["쑥라떼", "대추차"],
        adapter=adapter,
        today=week_b,
    )

    # Second run with a different relative ordering: 대추차 now overtakes 쑥라떼.
    adapter2 = _FakeAdapter(
        [
            _series("쑥라떼", [(week_a, 50.0), (week_b, 40.0)]),
            _series("대추차", [(week_a, 90.0), (week_b, 95.0)]),
        ]
    )
    result = refresh_trends(
        db_session,
        watchlist=["쑥라떼", "대추차"],
        adapter=adapter2,
        today=week_b,
    )

    assert result.inserted == 0
    assert result.updated == 2
    rows = db_session.query(Trend).filter(Trend.week_of == week_b).all()
    assert len(rows) == 2
    sukra = next(r for r in rows if r.keyword == "쑥라떼")
    daechu = next(r for r in rows if r.keyword == "대추차")
    assert daechu.rank == 1
    assert sukra.rank == 2
    assert sukra.is_up is False  # 50 → 40
    assert daechu.is_up is True  # 90 → 95


def test_refresh_empty_series_is_noop(db_session: Session) -> None:
    adapter = _FakeAdapter([])
    result = refresh_trends(
        db_session,
        watchlist=["a"],
        adapter=adapter,
        today=date(2025, 5, 12),
    )
    assert result.week_of is None
    assert result.inserted == 0
    assert result.updated == 0
    assert db_session.query(Trend).count() == 0


def test_refresh_single_point_falls_back_to_zero_change(db_session: Session) -> None:
    week = date(2025, 5, 12)
    adapter = _FakeAdapter([_series("쑥라떼", [(week, 50.0)])])
    refresh_trends(db_session, watchlist=["쑥라떼"], adapter=adapter, today=week)
    row = db_session.query(Trend).one()
    assert row.change_percent == pytest.approx(0.0)
    assert row.is_up is True


def test_refresh_caps_to_top_n(db_session: Session) -> None:
    """Discovery hands back top-N; refresh only writes those rows.

    Larger candidate pool with more entries than top_n should still produce
    exactly top_n rows, ranked by score.
    """
    week_a, week_b = date(2025, 5, 5), date(2025, 5, 12)
    # 5 candidates, but top_n=3 — only the top 3 should land in the DB.
    adapter = _FakeAdapter(
        [
            _series("a", [(week_a, 10.0), (week_b, 90.0)]),  # +800% (clamped 200)
            _series("b", [(week_a, 50.0), (week_b, 60.0)]),  # +20%
            _series("c", [(week_a, 70.0), (week_b, 70.0)]),  # 0%
            _series("d", [(week_a, 80.0), (week_b, 40.0)]),  # -50%
            _series("e", [(week_a, 5.0), (week_b, 4.0)]),  # -20%, low absolute
        ]
    )
    result = refresh_trends(
        db_session,
        watchlist=["a", "b", "c", "d", "e"],
        adapter=adapter,
        top_n=3,
        today=week_b,
    )
    assert result.inserted == 3
    rows = db_session.query(Trend).order_by(Trend.rank.asc()).all()
    assert len(rows) == 3
    assert [r.rank for r in rows] == [1, 2, 3]
