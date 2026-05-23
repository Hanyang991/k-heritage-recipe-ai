"""``TrendCandidateProvider`` protocol — *what should we even consider ranking?*

PR #11 / PR #12 both rank a fixed pool (``DEFAULT_WATCHLIST``). That's a
**closed-pool discovery**: a brand new trending keyword that nobody put on the
watchlist can never surface. To do real "급상승" discovery we need a layer
*above* ``TrendKeywordDiscovery`` whose only job is to *suggest new keyword
candidates*, which the existing discovery then scores.

That's this protocol. Each provider returns a list of strings — *just the
keyword candidates*, no ratios, no rise %, no ranking. The downstream
``MultiSourceDiscovery`` dedupes the unions of all provider outputs, fetches
series via the injected ``TrendsAdapter``, and reuses PR #11's blended score
for the actual ranking.

The default ``StaticCandidateProvider`` wraps ``DEFAULT_WATCHLIST`` so the
existing curated pool is itself just one provider — sources A (Naver Shopping
Insight, PR #12), B (Google Trends, PR #13), C (Naver News, PR #14), D (LLM
expansion, PR #15) all plug in alongside it.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from app.services.trends.watchlist import DEFAULT_WATCHLIST


class TrendCandidateProvider(Protocol):
    """Returns *just keyword strings* — series fetching happens elsewhere."""

    name: str

    def discover_candidates(
        self,
        today: date | None = None,
        limit: int = 50,
    ) -> list[str]:
        """Return at most ``limit`` deduplicated keyword candidates."""
        ...


class StaticCandidateProvider:
    """Wraps a fixed keyword list (e.g. ``DEFAULT_WATCHLIST``) as a provider.

    Makes the existing curated pool composable with open-discovery providers
    in ``MultiSourceDiscovery`` without changing PR #11's behaviour when used
    standalone (``CuratedWatchlistDiscovery`` still uses the raw list).
    """

    name = "static"

    def __init__(
        self,
        keywords: list[str] | None = None,
    ) -> None:
        self._keywords = list(keywords) if keywords is not None else list(DEFAULT_WATCHLIST)

    def discover_candidates(
        self,
        today: date | None = None,  # noqa: ARG002 — match protocol
        limit: int = 50,
    ) -> list[str]:
        return list(self._keywords)[:limit] if limit else list(self._keywords)
