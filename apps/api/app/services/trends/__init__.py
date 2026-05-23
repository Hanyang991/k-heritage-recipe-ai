"""Trend data adapter + discovery factories.

Two layers, both swappable via env vars:

- ``TrendsAdapter`` answers "give me ratios for these keywords".
  ``TRENDS_PROVIDER=mock|live`` picks ``MockTrendsAdapter`` (default) vs
  ``NaverDatalabAdapter`` (검색어 트렌드).
- ``TrendKeywordDiscovery`` answers "which keywords should we surface".
  ``TRENDS_DISCOVERY_SOURCE=curated|shopping_insight`` picks
  ``CuratedWatchlistDiscovery`` (default, runs over ``TrendsAdapter``) vs
  ``NaverShoppingInsightDiscovery`` (its own shopping-intent adapter).

Mock mode for shopping_insight reuses ``MockTrendsAdapter`` so dev/CI never
needs Naver credentials; only ``TRENDS_PROVIDER=live`` activates the live
shopping insight endpoint.
"""

from functools import lru_cache

from app.config import get_settings
from app.services.trends.base import (
    TrendDataPoint,
    TrendKeywordSeries,
    TrendsAdapter,
    TrendsAdapterError,
)
from app.services.trends.discovery import (
    CuratedWatchlistDiscovery,
    DiscoveredKeyword,
    TrendKeywordDiscovery,
)
from app.services.trends.mock import MockTrendsAdapter
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

    return CuratedWatchlistDiscovery(get_trends_adapter())


__all__ = [
    "CuratedWatchlistDiscovery",
    "DiscoveredKeyword",
    "FOOD_CATEGORY_CODE",
    "NaverShoppingInsightAdapter",
    "NaverShoppingInsightDiscovery",
    "TrendDataPoint",
    "TrendKeywordDiscovery",
    "TrendKeywordSeries",
    "TrendsAdapter",
    "TrendsAdapterError",
    "get_trend_discovery",
    "get_trends_adapter",
]
