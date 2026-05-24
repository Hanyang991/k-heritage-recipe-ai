"""``MultiSourceDiscovery`` — fan-in over multiple ``TrendCandidateProvider`` sources.

Three-stage pipeline, all the same scoring/ranking math as
``CuratedWatchlistDiscovery`` so cross-source ranks are directly comparable:

1. **Gather**: call every provider's ``discover_candidates`` and merge into a
   single deduplicated pool. First-emitter wins for primary source
   attribution; ``discover_with_breakdown`` (PR #16) additionally returns
   the *full* set of sources that emitted each keyword so admins can audit
   which open-discovery layer is paying for itself.
2. **Score**: hand the merged pool to the injected ``TrendsAdapter`` for
   series data, using the same week-window + clamp parameters as the curated
   discovery so cross-source ranks are directly comparable.
3. **Rank**: blended (popularity weight × current_ratio) + (rise weight ×
   clamped rise %) — identical to PR #11.

Failures in any single provider degrade gracefully: the exception is logged,
captured in ``ProviderBreakdown.error`` (for the debug endpoint), and the
offending provider contributes zero candidates for that refresh. Open
discovery providers are *optional*; we'd rather ship a refresh missing
Google Trends candidates than fail the whole job.

``discover()`` is the production hot path that drops the breakdown info and
just returns the ranked top-N (preserves the old ``TrendKeywordDiscovery``
shape). ``discover_with_breakdown()`` is the debug-friendly variant used by
``GET /v1/admin/trends/debug`` — it returns the same ranked top-N plus
per-provider stats (raw candidate count, elapsed ms, exception text) and
the all-sources map for each ranked keyword. Both share the same underlying
gather→score→rank work via the private ``_gather_and_score`` helper.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.services.trends.base import TrendsAdapter
from app.services.trends.candidates import TrendCandidateProvider
from app.services.trends.discovery import DiscoveredKeyword, _blended_score

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderBreakdown:
    """Per-provider gather stats for ``GET /v1/admin/trends/debug``."""

    name: str
    candidate_count: int
    candidates_sample: tuple[str, ...]
    elapsed_ms: int
    error: str | None = None


@dataclass(frozen=True)
class MultiSourceBreakdown:
    """Diagnostic snapshot of one ``MultiSourceDiscovery.discover`` call."""

    providers: tuple[ProviderBreakdown, ...]
    unique_candidate_count: int
    scored_count: int
    ranked: tuple[DiscoveredKeyword, ...]
    keyword_sources: dict[str, tuple[str, ...]] = field(default_factory=dict)


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
        return list(self.discover_with_breakdown(today=today, limit=limit).ranked)

    def discover_with_breakdown(
        self,
        today: date | None = None,
        limit: int = 20,
        *,
        sample_size: int = 20,
    ) -> MultiSourceBreakdown:
        """Same pipeline as ``discover`` plus per-provider diagnostics.

        ``sample_size`` caps the per-provider ``candidates_sample`` payload
        so the admin debug response stays small even when one provider
        (e.g. ``static`` with 100+ items) dwarfs the others.
        """
        end = today or date.today()
        start = end - timedelta(weeks=self._weeks)

        # 1. Gather candidates per provider; capture timing, sample, and
        #    error so the admin debug endpoint can show what each layer
        #    contributed (or didn't).
        keyword_first_source: dict[str, str] = {}
        keyword_all_sources: dict[str, list[str]] = {}
        merged: list[str] = []
        breakdown_rows: list[ProviderBreakdown] = []
        for provider in self._providers:
            start_ns = time.perf_counter_ns()
            error: str | None = None
            emitted: list[str] = []
            try:
                emitted = provider.discover_candidates(
                    today=today, limit=self._candidates_per_provider
                )
            except Exception as exc:
                logger.exception(
                    "provider %r failed during candidate gathering — skipping",
                    provider.name,
                )
                error = f"{type(exc).__name__}: {exc}"[:300]
            elapsed_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
            for kw in emitted:
                if not kw:
                    continue
                if kw not in keyword_first_source:
                    keyword_first_source[kw] = provider.name
                    keyword_all_sources[kw] = [provider.name]
                    merged.append(kw)
                elif provider.name not in keyword_all_sources[kw]:
                    keyword_all_sources[kw].append(provider.name)
            breakdown_rows.append(
                ProviderBreakdown(
                    name=provider.name,
                    candidate_count=len(emitted),
                    candidates_sample=tuple(emitted[:sample_size]),
                    elapsed_ms=int(elapsed_ms),
                    error=error,
                )
            )

        if not merged:
            return MultiSourceBreakdown(
                providers=tuple(breakdown_rows),
                unique_candidate_count=0,
                scored_count=0,
                ranked=(),
                keyword_sources={},
            )

        # 2. Single adapter call for the whole merged pool (the adapter
        #    handles chunking internally).
        series = self._adapter.fetch_series(merged, start, end, "week")

        # 3. Blended scoring — same formula as CuratedWatchlistDiscovery so
        #    the merged debug view can compare across discovery sources.
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
                    source=keyword_first_source.get(s.keyword, self.name),
                    current_ratio=current,
                    rise_percent=round(rise_pct, 2),
                )
            )
        scored.sort(key=lambda d: (-d.score, d.keyword))
        ranked = scored[:limit]
        ranked_keywords = {k.keyword for k in ranked}
        sources_for_ranked = {
            kw: tuple(keyword_all_sources[kw])
            for kw in ranked_keywords
            if kw in keyword_all_sources
        }
        return MultiSourceBreakdown(
            providers=tuple(breakdown_rows),
            unique_candidate_count=len(merged),
            scored_count=len(scored),
            ranked=tuple(ranked),
            keyword_sources=sources_for_ranked,
        )
