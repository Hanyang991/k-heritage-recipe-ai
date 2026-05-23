"""``MultiSourceDiscovery`` — fan-in over multiple ``TrendCandidateProvider`` sources.

The shape is intentionally parallel to ``CuratedWatchlistDiscovery`` (PR #11)
so PR #16's merging service can treat them interchangeably:

1. **Gather**: call every provider's ``discover_candidates`` and merge into a
   single deduplicated pool. First-emitter wins for source attribution — if
   ``static`` and ``google_trends_daily`` both emit "쑥라떼", it's tagged as
   coming from ``static`` because that provider was registered first.
2. **Score**: hand the merged pool to the injected ``TrendsAdapter`` for
   series data, using the same week-window + clamp parameters as the curated
   discovery so cross-source ranks are directly comparable.
3. **Rank**: blended (popularity weight × current_ratio) + (rise weight ×
   clamped rise %) — identical to PR #11.

Failures in any single provider degrade gracefully: an exception is logged
and the offending provider contributes zero candidates for that refresh.
Open-discovery providers are *optional*; we'd rather ship a refresh missing
Google Trends candidates than fail the whole job.

The class deliberately does **not** subclass ``CuratedWatchlistDiscovery``
or share its instance state — the only thing shared is the
``_blended_score`` helper, which is intentional so PR #16 can rewrite this
class without touching the simpler curated path.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from app.services.trends.base import TrendsAdapter
from app.services.trends.candidates import TrendCandidateProvider
from app.services.trends.discovery import DiscoveredKeyword, _blended_score

logger = logging.getLogger(__name__)


class MultiSourceDiscovery:
    """Discovery over the union of candidates emitted by multiple providers."""

    name = "multi_source"

    def __init__(
        self,
        adapter: TrendsAdapter,
        providers: list[TrendCandidateProvider],
        *,
        weeks: int = 8,
        current_weight: float = 0.4,
        rise_weight: float = 0.6,
        rise_floor: float = -100.0,
        rise_ceiling: float = 200.0,
        candidates_per_provider: int = 200,
    ) -> None:
        if not providers:
            raise ValueError("MultiSourceDiscovery requires at least one provider")
        self._adapter = adapter
        self._providers = list(providers)
        self._weeks = weeks
        self._current_weight = current_weight
        self._rise_weight = rise_weight
        self._rise_floor = rise_floor
        self._rise_ceiling = rise_ceiling
        self._candidates_per_provider = candidates_per_provider

    @property
    def providers(self) -> list[TrendCandidateProvider]:
        return list(self._providers)

    def discover(
        self,
        today: date | None = None,
        limit: int = 20,
    ) -> list[DiscoveredKeyword]:
        end = today or date.today()
        start = end - timedelta(weeks=self._weeks)

        # 1. Gather candidates, preserving first-provider attribution.
        keyword_source: dict[str, str] = {}
        merged: list[str] = []
        for provider in self._providers:
            try:
                emitted = provider.discover_candidates(
                    today=today, limit=self._candidates_per_provider
                )
            except Exception:
                logger.exception(
                    "provider %r failed during candidate gathering — skipping",
                    provider.name,
                )
                continue
            for kw in emitted:
                if kw and kw not in keyword_source:
                    keyword_source[kw] = provider.name
                    merged.append(kw)

        if not merged:
            return []

        # 2. Single adapter call for the whole merged pool (the adapter
        #    handles chunking internally).
        series = self._adapter.fetch_series(merged, start, end, "week")

        # 3. Blended scoring — same formula as CuratedWatchlistDiscovery so
        #    PR #16 (merging service) can compare across discovery sources.
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
                    source=keyword_source.get(s.keyword, self.name),
                    current_ratio=current,
                    rise_percent=round(rise_pct, 2),
                )
            )
        scored.sort(key=lambda d: (-d.score, d.keyword))
        return scored[:limit]
