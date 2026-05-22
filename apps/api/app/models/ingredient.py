"""Ingredient master + recipe-ingredient join table."""

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Ingredient(Base, TimestampMixin):
    __tablename__ = "ingredients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(60), default="")
    default_unit: Mapped[str] = mapped_column(String(20), default="g")


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.id"), primary_key=True)
    ingredient_id: Mapped[str] = mapped_column(ForeignKey("ingredients.id"), primary_key=True)
    amount: Mapped[str] = mapped_column(String(60), default="", doc="Free-form amount string")
    note: Mapped[str] = mapped_column(String(255), default="")
    sort_order: Mapped[int] = mapped_column(default=0)

    recipe = relationship("Recipe", back_populates="ingredients")
    ingredient = relationship("Ingredient")
