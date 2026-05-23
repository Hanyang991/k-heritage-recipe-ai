"""Naver Shopping Insight adapter + discovery (source A).

Docs: https://developers.naver.com/docs/serviceapi/datalab/shopping/shopping.md

Where this differs from ``naver.py`` (검색어 트렌드):

- **Different signal.** Shopping Insight reports the relative popularity of a
  keyword among *shopping* queries (Naver 쇼핑 검색창), not general web search.
  In practice these diverge — e.g. "추석 선물" spikes on Shopping Insight
  weeks before it shows up in general DataLab Search. That is precisely why
  it's worth carrying both as independent discovery sources.
- **Category-scoped.** Every call is constrained to one Shopping Insight
  category code (default ``50000006`` = 식품). The adapter therefore takes
  the category code at construction time; multi-category coverage is achieved
  by composing multiple adapter instances at a higher layer.
- **Same auth.** Uses the same Naver Developers app client ID / secret as
  ``NaverDatalabAdapter`` (PR #11). The app just needs the "데이터랩
  (쇼핑인사이트)" API enabled in Naver Developers → 사용 API.

Endpoint: ``POST {base_url}/v1/datalab/shopping/category/keywords``
Auth: ``X-Naver-Client-Id`` + ``X-Naver-Client-Secret`` headers.
Limits: max 5 keyword groups per request (same chunking as DataLab Search).

``NaverShoppingInsightDiscovery`` wraps the adapter under the
``TrendKeywordDiscovery`` protocol (PR #11). It reuses the same blended
popularity + rise scoring as ``CuratedWatchlistDiscovery`` so PR #14 can
merge sources fairly, with one extra step: candidates whose Shopping
Insight ratio is zero throughout the window are filtered out (Shopping
Insight returns a flat-zero series for long-tail keywords that have no
shopping queries, and ranking those by week-over-week % is meaningless).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import httpx

from app.services.trends.base import (
    TimeUnit,
    TrendDataPoint,
    TrendKeywordSeries,
    TrendsAdapter,
    TrendsAdapterError,
)
from app.services.trends.discovery import (
    DiscoveredKeyword,
    _blended_score,
)
from app.services.trends.watchlist import DEFAULT_WATCHLIST

logger = logging.getLogger(__name__)

_MAX_GROUPS_PER_REQUEST = 5
_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Naver Shopping Insight top-level category codes (8-digit). Full list is on
# the DataLab Shopping Insight UI; we only hard-code the one this project
# defaults to so misconfiguration surfaces as an obviously-wrong constant
# rather than a silent zero-result response.
FOOD_CATEGORY_CODE = "50000006"
"""``식품`` (food) category — the default for K-heritage dessert/drink keywords."""


class NaverShoppingInsightAdapter:
    """``TrendsAdapter`` backed by Naver Shopping Insight's category-keyword endpoint."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        category_code: str = FOOD_CATEGORY_CODE,
        base_url: str = "https://openapi.naver.com",
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._category_code = category_code
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def category_code(self) -> str:
        return self._category_code

    def fetch_series(
        self,
        keywords: list[str],
        start: date,
        end: date,
        time_unit: TimeUnit = "week",
    ) -> list[TrendKeywordSeries]:
        if not keywords:
            return []
        merged: list[TrendKeywordSeries] = []
        with httpx.Client(timeout=self._timeout) as client:
            for chunk in _chunk(keywords, _MAX_GROUPS_PER_REQUEST):
                merged.extend(self._fetch_chunk(client, chunk, start, end, time_unit))
        return merged

    def _fetch_chunk(
        self,
        client: httpx.Client,
        keywords: list[str],
        start: date,
        end: date,
        time_unit: TimeUnit,
    ) -> list[TrendKeywordSeries]:
        body: dict[str, Any] = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "timeUnit": time_unit,
            "category": self._category_code,
            "keyword": [{"name": kw, "param": [kw]} for kw in keywords],
        }
        try:
            resp = client.post(
                f"{self._base_url}/v1/datalab/shopping/category/keywords",
                json=body,
                headers={
                    "X-Naver-Client-Id": self._client_id,
                    "X-Naver-Client-Secret": self._client_secret,
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            raise TrendsAdapterError(f"Naver Shopping Insight request failed: {exc}") from exc

        if resp.status_code == 401:
            raise TrendsAdapterError("Naver Shopping Insight rejected credentials (401)")
        if resp.status_code == 403:
            # Distinct from 401: keys are valid but the Shopping Insight API is
            # not enabled on the Naver Developers app. Surface it explicitly so
            # the operator knows to flip the toggle vs. rotate the key.
            raise TrendsAdapterError(
                "Naver Shopping Insight rejected request (403) — check that the "
                "'데이터랩(쇼핑인사이트)' API is enabled on the Naver Developers app"
            )
        if resp.status_code == 429:
            raise TrendsAdapterError("Naver Shopping Insight rate limit exceeded (429)")
        if resp.status_code >= 400:
            raise TrendsAdapterError(
                f"Naver Shopping Insight returned {resp.status_code}: {resp.text[:200]}"
            )

        return _parse_response(resp.json())


class NaverShoppingInsightDiscovery:
    """Discovery over a curated candidate pool using shopping-intent series.

    Mechanically identical to ``CuratedWatchlistDiscovery``: pull the last-N
    weeks for each candidate, then rank by ``current * w_c + rise % * w_r``.
    The only behavior delta is the empty-volume filter — Shopping Insight
    returns a flat-zero series for keywords with no shopping queries, and
    those entries get dropped instead of being ranked at score 0.
    """

    name = "shopping_insight"

    def __init__(
        self,
        adapter: TrendsAdapter,
        candidates: list[str] | None = None,
        *,
        weeks: int = 8,
        current_weight: float = 0.4,
        rise_weight: float = 0.6,
        rise_floor: float = -100.0,
        rise_ceiling: float = 200.0,
        min_peak_ratio: float = 0.0,
    ) -> None:
        self._adapter = adapter
        self._candidates = list(candidates) if candidates is not None else list(DEFAULT_WATCHLIST)
        self._weeks = weeks
        self._current_weight = current_weight
        self._rise_weight = rise_weight
        self._rise_floor = rise_floor
        self._rise_ceiling = rise_ceiling
        self._min_peak_ratio = min_peak_ratio

    @property
    def candidates(self) -> list[str]:
        return list(self._candidates)

    def discover(
        self,
        today: date | None = None,
        limit: int = 20,
    ) -> list[DiscoveredKeyword]:
        end = today or date.today()
        start = end - timedelta(weeks=self._weeks)
        series = self._adapter.fetch_series(self._candidates, start, end, "week")

        scored: list[DiscoveredKeyword] = []
        for s in series:
            ordered = sorted(s.data, key=lambda p: p.period)
            if not ordered:
                continue
            peak = max(p.ratio for p in ordered)
            if peak <= self._min_peak_ratio:
                continue
            current = ordered[-1].ratio
            previous = ordered[-2].ratio if len(ordered) >= 2 else current
            rise_pct = ((current - previous) / previous * 100.0) if previous > 0 else 0.0
            score = _blended_score(
                current,
                rise_pct,
                current_weight=self._current_weight,
                rise_weight=self._rise_weight,
                rise_floor=self._rise_floor,
                rise_ceiling=self._rise_ceiling,
            )
            scored.append(
                DiscoveredKeyword(
                    keyword=s.keyword,
                    score=round(score, 4),
                    source=self.name,
                    current_ratio=current,
                    rise_percent=round(rise_pct, 2),
                )
            )
        scored.sort(key=lambda d: (-d.score, d.keyword))
        return scored[:limit]


def _chunk(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _parse_response(payload: dict[str, Any]) -> list[TrendKeywordSeries]:
    out: list[TrendKeywordSeries] = []
    for entry in payload.get("results", []):
        title = entry.get("title", "")
        data_points: list[TrendDataPoint] = []
        for row in entry.get("data", []):
            period = row.get("period")
            ratio = row.get("ratio")
            if period is None or ratio is None:
                continue
            try:
                data_points.append(
                    TrendDataPoint(period=date.fromisoformat(period), ratio=float(ratio))
                )
            except (TypeError, ValueError):
                logger.warning("skipping malformed datapoint: %r", row)
                continue
        out.append(TrendKeywordSeries(keyword=title, data=tuple(data_points)))
    return out
