"""Pydantic schemas for the favorite-keyword endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FavoriteKeywordCreate(BaseModel):
    """Body for ``POST /v1/private/me/favorite-keywords``."""

    keyword: str = Field(min_length=1, max_length=120)

    @field_validator("keyword")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "keyword must not be empty"
            raise ValueError(msg)
        return cleaned


class FavoriteKeyword(BaseModel):
    """One starred keyword as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    keyword: str
    created_at: datetime
