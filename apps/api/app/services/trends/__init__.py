"""Trend data adapter + discovery factories.

Two layers, both swappable via env vars:

- ``TrendsAdapter`` answers "give me ratios for these keywords".
  ``TRENDS_PROVIDER=mock|live`` picks ``MockTrendsAdapter`` (default) vs
  ``NaverDatalabAdapter`` (검색어 트렌드).
- ``TrendKeywordDiscovery`` answers "which keywords should we surface".
  ``TRENDS_DISCOVERY_SOURCE=curated|shopping_insight|open`` picks
  ``CuratedWatchlistDiscovery`` (default, closed pool),
  ``NaverShoppingInsightDiscovery`` (closed pool, shopping intent), or
  ``MultiSourceDiscovery`` (open pool — static watchlist plus open-discovery
  providers like Google Trends).

Mock mode for shopping_insight reuses ``MockTrendsAdapter`` so dev/CI never
needs Naver credentials; only ``TRENDS_PROVIDER=live`` activates the live
shopping insight endpoint. ``open`` discovery providers (Google Trends today,
Naver News + LLM in later PRs) make their own HTTP calls and degrade to
zero candidates on any failure so the refresh job stays robust.
"""

from functools import lru_cache

from app.config import get_settings
from app.services.trends.base import (
    TrendDataPoint,
    TrendKeywordSeries,
    TrendsAdapter,
    TrendsAdapterError,
)
from app.services.trends.candidates import (
    StaticCandidateProvider,
    TrendCandidateProvider,
)
from app.services.trends.discovery import (
    CuratedWatchlistDiscovery,
    DiscoveredKeyword,
    TrendKeywordDiscovery,
)
from app.services.trends.food_filter import filter_food_keywords, is_food_keyword
from app.services.trends.google_trends import GoogleTrendsCandidateProvider
from app.services.trends.mock import MockTrendsAdapter
from app.services.trends.multi_source import MultiSourceDiscovery
from app.services.trends.naver import NaverDatalabAdapter
from app.services.trends.shopping_insight import (
    FOOD_CATEGORY_CODE,
    NaverShoppingInsightAdapter,
    NaverShoppingInsightDiscovery,
)


@lru_cache
def get_trends_adapter() -> TrendsAdapter:
    settings = get_settings()
    if settings.trends_provider == "live":
        if not (settings.naver_datalab_client_id and settings.naver_datalab_client_secret):
            raise TrendsAdapterError(
                "TRENDS_PROVIDER=live requires NAVER_DATALAB_CLIENT_ID + "
                "NAVER_DATALAB_CLIENT_SECRET"
            )
        return NaverDatalabAdapter(
            client_id=settings.naver_datalab_client_id,
            client_secret=settings.naver_datalab_client_secret,
            base_url=settings.naver_datalab_base_url,
        )
    return MockTrendsAdapter()


@lru_cache
def get_trend_discovery() -> TrendKeywordDiscovery:
    """Pick the discovery source from ``TRENDS_DISCOVERY_SOURCE``.

    - ``curated`` (default): ``CuratedWatchlistDiscovery`` over the adapter
      returned by ``get_trends_adapter``.
    - ``shopping_insight``: ``NaverShoppingInsightDiscovery``. In live mode
      uses a dedicated ``NaverShoppingInsightAdapter`` (shopping-intent
      signal); in mock mode reuses ``MockTrendsAdapter`` so dev/CI doesn't
      need network or credentials.
    - ``open``: ``MultiSourceDiscovery`` over the curated static watchlist
      plus enabled open-discovery providers (Google Trends today, Naver
      News + LLM expansion in later PRs). Open providers degrade to zero
      candidates on failure; series fetching uses the same adapter as
      ``curated`` so the upstream Naver toggle still applies.
    """
    settings = get_settings()
    if settings.trends_discovery_source == "shopping_insight":
        if settings.trends_provider == "live":
            if not (settings.naver_datalab_client_id and settings.naver_datalab_client_secret):
                raise TrendsAdapterError(
                    "TRENDS_DISCOVERY_SOURCE=shopping_insight with "
                    "TRENDS_PROVIDER=live requires NAVER_DATALAB_CLIENT_ID + "
                    "NAVER_DATALAB_CLIENT_SECRET"
                )
            adapter: TrendsAdapter = NaverShoppingInsightAdapter(
                client_id=settings.naver_datalab_client_id,
                client_secret=settings.naver_datalab_client_secret,
                category_code=settings.naver_shopping_insight_category_code,
                base_url=settings.naver_datalab_base_url,
            )
        else:
            adapter = MockTrendsAdapter()
        return NaverShoppingInsightDiscovery(adapter)

    if settings.trends_discovery_source == "open":
        providers: list[TrendCandidateProvider] = [StaticCandidateProvider()]
        if settings.trends_open_google_enabled:
            providers.append(
                GoogleTrendsCandidateProvider(
                    geo=settings.google_trends_geo,
                    hl=settings.google_trends_hl,
                )
            )
        return MultiSourceDiscovery(get_trends_adapter(), providers)

    return CuratedWatchlistDiscovery(get_trends_adapter())


__all__ = [
    "CuratedWatchlistDiscovery",
    "DiscoveredKeyword",
    "FOOD_CATEGORY_CODE",
    "GoogleTrendsCandidateProvider",
    "MultiSourceDiscovery",
    "NaverShoppingInsightAdapter",
    "NaverShoppingInsightDiscovery",
    "StaticCandidateProvider",
    "TrendCandidateProvider",
    "TrendDataPoint",
    "TrendKeywordDiscovery",
    "TrendKeywordSeries",
    "TrendsAdapter",
    "TrendsAdapterError",
    "filter_food_keywords",
    "get_trend_discovery",
    "get_trends_adapter",
    "is_food_keyword",
]
