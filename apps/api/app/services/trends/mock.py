"""Deterministic mock trends adapter (no network).

Returns a smooth-ish synthetic time-series keyed off ``hash(keyword)`` so the
output is stable across test runs and across machines. Used whenever
``TRENDS_PROVIDER`` is unset or ``mock`` — i.e. local dev, CI, and tests.
"""

from __future__ import annotations

import hashlib
import math
from datetime import date, timedelta

from app.services.trends.base import (
    TimeUnit,
    TrendDataPoint,
    TrendKeywordSeries,
)

_UNIT_STEP_DAYS: dict[TimeUnit, int] = {"date": 1, "week": 7, "month": 30}


def _seed(keyword: str) -> int:
    h = hashlib.sha1(keyword.encode("utf-8")).digest()
    return int.from_bytes(h[:4], "big")


def _ratio(keyword: str, idx: int) -> float:
    """Synthetic 0..100 ratio. Two sine components keep curves visually distinct."""
    seed = _seed(keyword)
    phase = (seed % 360) * math.pi / 180
    base = 50 + 35 * math.sin(idx / 2.0 + phase)
    wobble = 8 * math.sin(idx / 5.0 + phase * 0.5)
    return round(max(0.0, min(100.0, base + wobble)), 2)


class MockTrendsAdapter:
    def fetch_series(
        self,
        keywords: list[str],
        start: date,
        end: date,
        time_unit: TimeUnit = "week",
    ) -> list[TrendKeywordSeries]:
        if not keywords:
            return []
        step = timedelta(days=_UNIT_STEP_DAYS[time_unit])
        out: list[TrendKeywordSeries] = []
        for kw in keywords:
            points: list[TrendDataPoint] = []
            cursor = start
            idx = 0
            while cursor <= end:
                points.append(TrendDataPoint(period=cursor, ratio=_ratio(kw, idx)))
                cursor += step
                idx += 1
            out.append(TrendKeywordSeries(keyword=kw, data=tuple(points)))
        return out
