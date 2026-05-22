"""Heritage adapter contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class HeritageDoc:
    """Document payload returned by a public-API adapter."""

    external_id: str
    title: str
    institution: str  # "jangseogak" | "nfm" | "culture"
    region: str
    period: str
    category: str
    year: int | None
    original_text: str
    summary: str
    license: str = "KOGL-1"


@dataclass
class DocumentMatch:
    document: HeritageDoc
    match_score: float


class HeritageAdapter(Protocol):
    def search(
        self,
        keyword: str,
        region: str | None = None,
        period: str | None = None,
        limit: int = 10,
    ) -> list[DocumentMatch]:
        """Top-K matched documents from all integrated archives."""

    def list_seeded(self) -> list[HeritageDoc]:
        """All seed documents (used by the seed script)."""
