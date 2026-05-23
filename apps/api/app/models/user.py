"""User model — service accounts and their subscription plan."""

import enum
import uuid

from sqlalchemy import JSON, Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class UserRole(enum.StrEnum):
    USER = "user"
    ADMIN = "admin"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.USER, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Onboarding / persona (spec §8.2.1)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    persona: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    preferred_regions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    preferred_keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    subscription = relationship(
        "Subscription", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    recipes = relationship("Recipe", back_populates="user", cascade="all, delete-orphan")
