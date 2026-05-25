"""SQLAlchemy ORM models.

Import every model here so Alembic / Base.metadata.create_all picks them up.
"""

from app.models.document import Document
from app.models.favorite_keyword import UserFavoriteKeyword
from app.models.ingredient import Ingredient, RecipeIngredient
from app.models.notification import Notification, NotificationType
from app.models.recipe import Recipe, RecipeStatus
from app.models.subscription import Plan, Subscription
from app.models.trend import Trend
from app.models.user import User, UserRole
from app.models.vector_search_datapoint import VectorSearchDatapoint

__all__ = [
    "Document",
    "Ingredient",
    "Notification",
    "NotificationType",
    "Plan",
    "Recipe",
    "RecipeIngredient",
    "RecipeStatus",
    "Subscription",
    "Trend",
    "User",
    "UserFavoriteKeyword",
    "UserRole",
    "VectorSearchDatapoint",
]
