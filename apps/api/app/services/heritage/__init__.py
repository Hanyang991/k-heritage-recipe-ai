"""Heritage data adapter factory (장서각 / 국립민속박물관 / 문화데이터광장).

Live mode currently wires the 장서각 open API only. The 국립민속박물관 and
문화데이터광장 adapters are scheduled for Phase 3 per the tech spec; the
factory falls back to the mock for any institution not yet implemented so
the mode flag stays binary (mock / live) instead of multi-state.
"""

from functools import lru_cache

from app.config import get_settings
from app.services.heritage.base import HeritageAdapter
from app.services.heritage.jangseogak import JangseogakSearchClient
from app.services.heritage.live import LiveHeritageAdapter
from app.services.heritage.mock import MockHeritageAdapter


@lru_cache
def get_heritage_adapter() -> HeritageAdapter:
    settings = get_settings()
    if settings.heritage_provider == "live":
        client = JangseogakSearchClient(base_url=settings.jangseogak_base_url)
        return LiveHeritageAdapter(client=client)
    return MockHeritageAdapter()


__all__ = [
    "HeritageAdapter",
    "LiveHeritageAdapter",
    "MockHeritageAdapter",
    "get_heritage_adapter",
]
