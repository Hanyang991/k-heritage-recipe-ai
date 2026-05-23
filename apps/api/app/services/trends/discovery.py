"""Trend keyword discovery — surface what's *trending* from a candidate pool.

The previous ``TrendsAdapter`` answers "what is the weekly ratio for these
keywords I already know about". Discovery answers the harder question:
*"which keywords should the dashboard be showing right now?"* — a separate
concern that lets us swap in different discovery sources (curated pool today,
Naver Shopping Insight category ranks tomorrow, Google Trends after that)
without touching the persistence / API layers.

The default ``CuratedWatchlistDiscovery`` ranks a curated candidate pool
(``DEFAULT_WATCHLIST``) by a blended **popularity + rise** score so the
dashboard can claim "급상승" honestly: a keyword has to be either popular *or*
moving up week-over-week to surface, and stable-but-popular vs small-but-
spiking get treated comparably.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from app.services.trends.base import TrendsAdapter
from app.services.trends.watchlist import DEFAULT_WATCHLIST


@dataclass(frozen=True)
class DiscoveredKeyword:
    """One ranked candidate from a discovery source.

    ``score`` is the source-specific ranking key — higher = more "trending".
    ``current_ratio`` / ``rise_percent`` are filled in when the source has
    series-level info (so the refresh job doesn't need to re-fetch); other
    discovery sources may leave them ``None``.
    """

    keyword: str
    score: float
    source: str
    current_ratio: float | None = None
    rise_percent: float | None = None


class TrendKeywordDiscovery(Protocol):
    """Protocol every discovery source implements."""

    name: str

    def discover(
        self,
        today: date | None = None,
        limit: int = 20,
    ) -> list[DiscoveredKeyword]:
        """Return up to ``limit`` candidates ranked descending by ``score``."""
        ...


def _blended_score(
    current_ratio: float,
    rise_percent: float,
    *,
    current_weight: float,
    rise_weight: float,
    rise_floor: float,
    rise_ceiling: float,
) -> float:
    """Blend the two signals so neither dominates pathologically.

    Clamping rise % avoids a tiny base (e.g. ratio 0.5 → 5, +900%) drowning
    out genuinely popular keywords; floor avoids long-tail dropouts dragging
    others down by an arbitrary amount.
    """
    rise_clamped = max(rise_floor, min(rise_percent, rise_ceiling))
    return current_ratio * current_weight + rise_clamped * rise_weight


class CuratedWatchlistDiscovery:
    """Discovery from a curated candidate pool, ranked by ratio + rise.

    Calls the injected ``TrendsAdapter`` once for the full candidate pool to
    get last-N-week series, then ranks each candidate by a blended score.
    """

    name = "curated"

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
    ) -> None:
        self._adapter = adapter
        self._candidates = list(candidates) if candidates is not None else list(DEFAULT_WATCHLIST)
        self._weeks = weeks
        self._current_weight = current_weight
        self._rise_weight = rise_weight
        self._rise_floor = rise_floor
        self._rise_ceiling = rise_ceiling

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
