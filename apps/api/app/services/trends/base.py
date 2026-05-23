"""Trends adapter contract.

Modeled after Naver DataLab's 검색어 트렌드 API: each adapter call takes a list
of keywords + a time range + a time unit (date / week / month) and returns one
``TrendKeywordSeries`` per keyword. ``ratio`` is the *relative* popularity
within the queried set, normalized so that the global peak across all returned
series for that single call is 100.

The router layer is responsible for translating series into the existing
weekly ``Trend`` snapshot rows (rank + change_percent vs previous week).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

TimeUnit = Literal["date", "week", "month"]


@dataclass(frozen=True)
class TrendDataPoint:
    period: date
    ratio: float


@dataclass(frozen=True)
class TrendKeywordSeries:
    keyword: str
    data: tuple[TrendDataPoint, ...]


class TrendsAdapterError(RuntimeError):
    """Raised when the upstream trends provider can't be reached or rejects us."""


class TrendsAdapter(Protocol):
    def fetch_series(
        self,
        keywords: list[str],
        start: date,
        end: date,
        time_unit: TimeUnit = "week",
    ) -> list[TrendKeywordSeries]:
        """Return one time-series per keyword across ``[start, end]``.

        Implementations may chunk large keyword lists to respect upstream limits
        (Naver DataLab caps keywordGroups at 5 per request).
        """
