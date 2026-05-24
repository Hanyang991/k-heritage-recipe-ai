"""In-app notification endpoints (`/v1/private/me/notifications`)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.notification import Notification as NotificationModel
from app.models.user import User
from app.schemas.notification import (
    Notification,
    NotificationListResponse,
    NotificationReadAllResponse,
)

router = APIRouter(prefix="/private/me/notifications", tags=["notifications"])


def _utcnow() -> datetime:
    return datetime.now(UTC)


@router.get("", response_model=NotificationListResponse)
def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationListResponse:
    """All notifications for the current user, newest first.

    Always returns ``unread_count`` alongside the items so the bell badge
    only needs one request.
    """
    base = (
        select(NotificationModel)
        .where(NotificationModel.user_id == current_user.id)
        .order_by(NotificationModel.created_at.desc())
    )
    if unread_only:
        base = base.where(NotificationModel.read_at.is_(None))
    rows = db.execute(base.limit(limit)).scalars().all()
    unread_count = db.execute(
        select(func.count())
        .select_from(NotificationModel)
        .where(
            NotificationModel.user_id == current_user.id,
            NotificationModel.read_at.is_(None),
        )
    ).scalar_one()
    return NotificationListResponse(
        items=[Notification.model_validate(r) for r in rows],
        unread_count=int(unread_count),
    )


@router.post("/{notification_id}/read", response_model=Notification)
def mark_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Notification:
    """Mark a single notification as read. Idempotent.

    Returns 404 if the notification belongs to a different user or doesn't
    exist — we don't leak the difference because in either case the current
    user has no business mutating it.
    """
    row = db.execute(
        select(NotificationModel).where(
            NotificationModel.id == notification_id,
            NotificationModel.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "NOTIFICATION_NOT_FOUND",
                "message": f"notification {notification_id} not found",
                "status": 404,
            },
        )
    if row.read_at is None:
        row.read_at = _utcnow()
        db.commit()
        db.refresh(row)
    return Notification.model_validate(row)


@router.post("/read-all", response_model=NotificationReadAllResponse)
def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationReadAllResponse:
    """Mark every currently-unread notification for the user as read."""
    result = db.execute(
        update(NotificationModel)
        .where(
            NotificationModel.user_id == current_user.id,
            NotificationModel.read_at.is_(None),
        )
        .values(read_at=_utcnow())
    )
    db.commit()
    return NotificationReadAllResponse(marked_read=int(result.rowcount or 0))
