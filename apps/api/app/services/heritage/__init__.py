"""Heritage data adapter factory (장서각 / 국립민속박물관 / 문화데이터광장)."""

from functools import lru_cache

from app.config import get_settings
from app.services.heritage.base import HeritageAdapter
from app.services.heritage.mock import MockHeritageAdapter


@lru_cache
def get_heritage_adapter() -> HeritageAdapter:
    settings = get_settings()
    if settings.heritage_provider == "live":
        raise NotImplementedError(
            "Live heritage API adapter is not yet wired. "
            "Use HERITAGE_PROVIDER=mock for development."
        )
    return MockHeritageAdapter()


__all__ = ["HeritageAdapter", "get_heritage_adapter"]
