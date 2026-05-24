"""Build the response payload for ``GET /v1/admin/trends/debug``.

Wraps every ``TrendKeywordDiscovery`` shape into the same diagnostics
schema. For ``MultiSourceDiscovery`` we call
``discover_with_breakdown`` directly so the response has true per-provider
counts, timings, and error text. For the simpler ``curated`` and
``shopping_insight`` discoveries (single internal pool, no per-provider
fan-in) we synthesize a single provider row from the ranked output —
the admin still gets the merged top-N and can confirm which mode is
active, without us pretending we have multi-source telemetry we don't.
"""

from __future__ import annotations

import time
from datetime import date

from app.schemas.trend import (
    TrendDebugProviderRow,
    TrendDebugRankedRow,
    TrendDebugResponse,
)
from app.services.trends.discovery import (
    CuratedWatchlistDiscovery,
    TrendKeywordDiscovery,
)
from app.services.trends.multi_source import MultiSourceDiscovery
from app.services.trends.shopping_insight import NaverShoppingInsightDiscovery

_SINGLE_SOURCE_SAMPLE_SIZE = 20


def build_debug_response(
    discovery: TrendKeywordDiscovery,
    *,
    today: date | None = None,
    limit: int = 20,
) -> TrendDebugResponse:
    ref_date = today or date.today()

    if isinstance(discovery, MultiSourceDiscovery):
        breakdown = discovery.discover_with_breakdown(today=ref_date, limit=limit)
        providers = [
            TrendDebugProviderRow(
                name=row.name,
                candidate_count=row.candidate_count,
                candidates_sample=list(row.candidates_sample),
                elapsed_ms=row.elapsed_ms,
                error=row.error,
            )
            for row in breakdown.providers
        ]
        ranked = [
            TrendDebugRankedRow(
                keyword=k.keyword,
                score=k.score,
                primary_source=k.source,
                all_sources=list(breakdown.keyword_sources.get(k.keyword, (k.source,))),
                current_ratio=k.current_ratio,
                rise_percent=k.rise_percent,
            )
            for k in breakdown.ranked
        ]
        return TrendDebugResponse(
            discovery_type=discovery.name,
            ref_date=ref_date,
            limit=limit,
            unique_candidate_count=breakdown.unique_candidate_count,
            scored_count=breakdown.scored_count,
            providers=providers,
            ranked=ranked,
        )

    # Single-source discoveries: time the one discover() call so the admin
    # at least sees how long the active source took, then synthesize one
    # provider row from the ranked output.
    start_ns = time.perf_counter_ns()
    ranked_raw = discovery.discover(today=ref_date, limit=limit)
    elapsed_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
    keywords = [k.keyword for k in ranked_raw]

    provider_name = _single_source_provider_name(discovery)
    provider_row = TrendDebugProviderRow(
        name=provider_name,
        candidate_count=_single_source_candidate_count(discovery, fallback=len(keywords)),
        candidates_sample=keywords[:_SINGLE_SOURCE_SAMPLE_SIZE],
        elapsed_ms=int(elapsed_ms),
        error=None,
    )
    ranked = [
        TrendDebugRankedRow(
            keyword=k.keyword,
            score=k.score,
            primary_source=k.source,
            all_sources=[k.source],
            current_ratio=k.current_ratio,
            rise_percent=k.rise_percent,
        )
        for k in ranked_raw
    ]
    return TrendDebugResponse(
        discovery_type=discovery.name,
        ref_date=ref_date,
        limit=limit,
        unique_candidate_count=provider_row.candidate_count,
        scored_count=len(ranked_raw),
        providers=[provider_row],
        ranked=ranked,
    )


def _single_source_provider_name(discovery: TrendKeywordDiscovery) -> str:
    if isinstance(discovery, CuratedWatchlistDiscovery):
        return "curated_watchlist"
    if isinstance(discovery, NaverShoppingInsightDiscovery):
        return "naver_shopping_insight"
    return discovery.name


def _single_source_candidate_count(discovery: TrendKeywordDiscovery, *, fallback: int) -> int:
    if isinstance(discovery, CuratedWatchlistDiscovery):
        return len(discovery.candidates)
    return fallback
