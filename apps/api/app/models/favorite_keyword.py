"""User-driven keyword favourites (star on a trend card)."""

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class UserFavoriteKeyword(Base, TimestampMixin):
    """One starred trend keyword for one user.

    Distinct from ``User.preferred_keywords`` (set during onboarding as a
    persona hint) — this table is built up over time by the user clicking
    the star button on trend cards and is the source of truth for future
    notification / alert features (PR C scope).
    """

    __tablename__ = "user_favorite_keywords"
    __table_args__ = (UniqueConstraint("user_id", "keyword", name="uq_user_favorite_keyword"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    keyword: Mapped[str] = mapped_column(String(120), nullable=False, index=True)

    user = relationship("User", backref="favorite_keywords")
