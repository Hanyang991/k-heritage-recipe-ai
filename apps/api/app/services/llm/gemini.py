"""Gemini-backed LLM adapter (live mode).

This is a thin scaffold — it raises `NotImplementedError` until a real
GEMINI_API_KEY is provided and the integration is wired up. The mock
adapter is the default and covers all functional tests.

When wiring this up:
    1. `pip install google-generativeai`
    2. Set `LLM_PROVIDER=live` and `GEMINI_API_KEY=...` in the env
    3. Implement `generate_recipes()` using the prompts in spec section 6.2
       with `response_schema` enforcement and `temperature=0.7`.
    4. Implement `translate_classical()` per spec section 6.1
       with `temperature=0.1` for translation consistency.
"""

from __future__ import annotations

from app.services.llm.base import (
    GeneratedRecipe,
    GenerateRecipesInput,
    LLMAdapter,
)


class GeminiLLMAdapter(LLMAdapter):
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY is required when LLM_PROVIDER=live. "
                "Set the env var or switch to LLM_PROVIDER=mock."
            )
        self._api_key = api_key

    def generate_recipes(self, payload: GenerateRecipesInput) -> list[GeneratedRecipe]:
        raise NotImplementedError(
            "Live Gemini integration is not yet wired. Use LLM_PROVIDER=mock for development."
        )

    def translate_classical(self, original: str) -> str:
        raise NotImplementedError(
            "Live Gemini integration is not yet wired. Use LLM_PROVIDER=mock for development."
        )
