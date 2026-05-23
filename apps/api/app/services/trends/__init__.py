"""Trend data adapter factory (Naver DataLab 검색어 트렌드)."""

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
    """Default discovery: curated pool ranked by ratio + rise via the adapter."""
    return CuratedWatchlistDiscovery(get_trends_adapter())


__all__ = [
    "CuratedWatchlistDiscovery",
    "DiscoveredKeyword",
    "TrendDataPoint",
    "TrendKeywordDiscovery",
    "TrendKeywordSeries",
    "TrendsAdapter",
    "TrendsAdapterError",
    "get_trend_discovery",
    "get_trends_adapter",
]
