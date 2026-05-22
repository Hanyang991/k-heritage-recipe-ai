"""Pydantic request/response schemas."""

from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.common import ErrorResponse
from app.schemas.document import DocumentMatch, DocumentOut
from app.schemas.recipe import (
    RecipeCandidate,
    RecipeDetailOut,
    RecipeGenerateRequest,
    RecipeGenerateResponse,
    RecipeListItem,
    RecipeStatusUpdate,
)
from app.schemas.trend import TrendOut
from app.schemas.user import SubscriptionOut, UserOut

__all__ = [
    "DocumentMatch",
    "DocumentOut",
    "ErrorResponse",
    "LoginRequest",
    "RecipeCandidate",
    "RecipeDetailOut",
    "RecipeGenerateRequest",
    "RecipeGenerateResponse",
    "RecipeListItem",
    "RecipeStatusUpdate",
    "RegisterRequest",
    "SubscriptionOut",
    "TokenResponse",
    "TrendOut",
    "UserOut",
]
