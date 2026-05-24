"""In-app notification rows surfaced to users from background jobs."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class NotificationType(enum.StrEnum):
    """The kind of event that produced a notification.

    Add new values here as more notification sources land; the frontend
    switches on this to pick an icon / wording / link target.
    """

    FAVORITE_KEYWORD_TRENDING = "favorite_keyword_trending"


class Notification(Base, TimestampMixin):
    """A single in-app notification for a single user.

    Notifications are write-only from the API surface — they're produced by
    background detectors (currently ``detect_favorite_keyword_notifications``
    invoked at the end of ``refresh_trends``) and only ever mutated by the
    user marking them as read.
    """

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[NotificationType] = mapped_column(Enum(NotificationType), nullable=False)
    # Free-form structured payload — the schema is owned by the detector
    # that emits each ``type``. For ``FAVORITE_KEYWORD_TRENDING`` we store
    # ``{"keyword": str, "rank": int, "previous_rank": int | null,
    #    "change_percent": float, "week_of": "YYYY-MM-DD"}``.
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    user = relationship("User", backref="notifications")
