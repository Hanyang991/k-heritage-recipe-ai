"""LLM adapter factory.

The adapter is selected by :attr:`Settings.llm_provider`:

* ``mock`` (default) — deterministic offline implementation used in dev / CI.
* ``live`` — :class:`GeminiLLMAdapter` against
  ``generativelanguage.googleapis.com`` (spec §6.1 / §6.2). Requires
  ``GEMINI_API_KEY``; when the key is absent the factory transparently
  degrades to the mock adapter (same graceful-degrade contract as the
  heritage NLK branch) so recipe-generate keeps working while the key
  is being provisioned.
"""

import logging
from functools import lru_cache

from app.config import get_settings
from app.services.llm.base import LLMAdapter
from app.services.llm.mock import MockLLMAdapter

logger = logging.getLogger(__name__)


@lru_cache
def get_llm_adapter() -> LLMAdapter:
    settings = get_settings()
    if settings.llm_provider != "live":
        return MockLLMAdapter()
    if not settings.gemini_api_key:
        # Graceful boot: log loudly but don't crash. Operators can
        # provision the key later without redeploying just because it's
        # absent today. This mirrors the heritage-NLK degrade path.
        logger.warning(
            "LLM_PROVIDER=live but GEMINI_API_KEY is unset; falling back to MockLLMAdapter"
        )
        return MockLLMAdapter()

    # Local import so the mock-only path doesn't import httpx-heavy module.
    from app.services.llm.gemini import GeminiLLMAdapter

    return GeminiLLMAdapter(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        base_url=settings.gemini_base_url,
        timeout=settings.gemini_request_timeout_seconds,
        recipe_max_tokens=settings.gemini_recipe_max_tokens,
        translate_max_tokens=settings.gemini_translate_max_tokens,
        recipe_temperature=settings.gemini_recipe_temperature,
        translate_temperature=settings.gemini_translate_temperature,
    )


__all__ = ["LLMAdapter", "get_llm_adapter"]
