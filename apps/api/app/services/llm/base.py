"""LLM adapter contract.

Recipes generated here flow through the FR-03 pipeline:
    vector_search(query) → matched_documents → LLM.generate_recipes(...) → 3 candidates
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class GeneratedRecipeStep:
    title: str
    description: str
    waiting: bool = False


@dataclass
class GeneratedIngredient:
    name: str
    amount: str
    note: str = ""


@dataclass
class GeneratedRecipe:
    name: str
    description: str
    region: str
    era: str
    diet: str
    menu_type: str
    keyword: str
    difficulty: str
    time_minutes: int
    servings: int
    estimated_cost_krw: int
    estimated_price_krw: int
    ingredients: list[GeneratedIngredient]
    steps: list[GeneratedRecipeStep]
    sns_caption: str
    source_attribution: str
    image_url: str
    is_recommended: bool


@dataclass
class GenerateRecipesInput:
    keyword: str
    region: str
    diet: str
    menu_type: str
    matched_documents: list[dict]  # raw doc payload for prompt context


class LLMAdapter(Protocol):
    """Contract every LLM provider must satisfy."""

    def generate_recipes(self, payload: GenerateRecipesInput) -> list[GeneratedRecipe]:
        """Return exactly 3 candidate recipes ordered by recommendation."""

    def translate_classical(self, original: str) -> str:
        """Translate Korean classical text to modern Korean (spec 6.1)."""
