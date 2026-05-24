"""Pydantic schemas for the notification endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.notification import NotificationType


class Notification(BaseModel):
    """One in-app notification."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    type: NotificationType
    payload: dict
    created_at: datetime
    read_at: datetime | None = None


class NotificationListResponse(BaseModel):
    """List response with a precomputed unread count.

    The frontend bell shows ``unread_count`` as a badge without needing a
    second roundtrip after listing.
    """

    items: list[Notification]
    unread_count: int


class NotificationReadAllResponse(BaseModel):
    """Result of ``POST /v1/private/me/notifications/read-all``."""

    marked_read: int
