"""Recipe model — AI-generated recipes saved per user."""

import enum
import uuid

from sqlalchemy import JSON, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class RecipeStatus(enum.StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FLAGGED = "flagged"


class Recipe(Base, TimestampMixin):
    __tablename__ = "recipes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    source_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id"), nullable=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")

    region: Mapped[str] = mapped_column(String(60), default="")
    era: Mapped[str] = mapped_column(String(60), default="")
    diet: Mapped[str] = mapped_column(String(60), default="")
    menu_type: Mapped[str] = mapped_column(String(60), default="")
    keyword: Mapped[str] = mapped_column(String(120), default="", index=True)

    difficulty: Mapped[str] = mapped_column(String(20), default="")
    time_minutes: Mapped[int] = mapped_column(Integer, default=0)
    servings: Mapped[int] = mapped_column(Integer, default=2)

    estimated_cost_krw: Mapped[int] = mapped_column(Integer, default=0)
    estimated_price_krw: Mapped[int] = mapped_column(Integer, default=0)

    steps: Mapped[list] = mapped_column(JSON, default=list)
    sns_caption: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(String(500), default="")

    source_attribution: Mapped[str] = mapped_column(Text, default="")
    is_recommended: Mapped[bool] = mapped_column(default=False)

    status: Mapped[RecipeStatus] = mapped_column(
        Enum(RecipeStatus), default=RecipeStatus.PENDING_REVIEW, nullable=False, index=True
    )
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    rating: Mapped[int] = mapped_column(Integer, default=0)
    is_selling: Mapped[bool] = mapped_column(default=False)

    # Recipe embedding (todo §1.4 vector variant). Populated by
    # :mod:`app.services.recipe_embeddings` on create + via the
    # ``backfill_recipe_embeddings`` job. JSON-backed for portability
    # (SQLite tests + Postgres prod both work off the same column);
    # Postgres deployments additionally mirror the values into a
    # ``vector(768)`` column with an HNSW cosine index — see
    # ``0003_recipe_embedding`` migration. Stays nullable so back-
    # catalogue recipes generated before the feature shipped don't
    # break the related-recipes endpoint (the service falls back to
    # the tag scorer in that case).
    embedding_values: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)

    user = relationship("User", back_populates="recipes")
    ingredients = relationship(
        "RecipeIngredient", back_populates="recipe", cascade="all, delete-orphan"
    )
    source_document = relationship("Document")
