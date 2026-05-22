"""LLM adapter factory.

The adapter is selected by `Settings.llm_provider`:
  - "mock"  → deterministic offline implementation (default)
  - "live"  → Gemini API (requires GEMINI_API_KEY)
"""

from functools import lru_cache

from app.config import get_settings
from app.services.llm.base import LLMAdapter
from app.services.llm.mock import MockLLMAdapter


@lru_cache
def get_llm_adapter() -> LLMAdapter:
    settings = get_settings()
    if settings.llm_provider == "live":
        from app.services.llm.gemini import GeminiLLMAdapter

        return GeminiLLMAdapter(api_key=settings.gemini_api_key)
    return MockLLMAdapter()


__all__ = ["LLMAdapter", "get_llm_adapter"]
