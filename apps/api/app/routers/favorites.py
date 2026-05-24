"""User favourite-keyword CRUD (`/v1/private/me/favorite-keywords`).

The starred set is the source of truth for upcoming notification features
(PR C scope) — it's intentionally separate from ``User.preferred_keywords``
which is set once during onboarding as a persona hint and never appended to.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.favorite_keyword import UserFavoriteKeyword
from app.models.user import User
from app.schemas.favorite_keyword import FavoriteKeyword, FavoriteKeywordCreate

router = APIRouter(prefix="/private/me/favorite-keywords", tags=["favorites"])


@router.get("", response_model=list[FavoriteKeyword])
def list_favorites(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[FavoriteKeyword]:
    """All keywords this user has starred, newest first."""
    rows = (
        db.execute(
            select(UserFavoriteKeyword)
            .where(UserFavoriteKeyword.user_id == current_user.id)
            .order_by(UserFavoriteKeyword.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [FavoriteKeyword.model_validate(r) for r in rows]


@router.post("", response_model=FavoriteKeyword, status_code=status.HTTP_201_CREATED)
def add_favorite(
    payload: FavoriteKeywordCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FavoriteKeyword:
    """Star a keyword. Idempotent: re-starring an already-starred keyword
    returns the existing row instead of erroring (so the UI star toggle
    doesn't need to know whether it was already favorited)."""
    existing = db.execute(
        select(UserFavoriteKeyword).where(
            UserFavoriteKeyword.user_id == current_user.id,
            UserFavoriteKeyword.keyword == payload.keyword,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return FavoriteKeyword.model_validate(existing)
    row = UserFavoriteKeyword(user_id=current_user.id, keyword=payload.keyword)
    db.add(row)
    db.commit()
    db.refresh(row)
    return FavoriteKeyword.model_validate(row)


@router.delete("/{keyword}", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite(
    keyword: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Unstar a keyword. 404 if it wasn't starred."""
    row = db.execute(
        select(UserFavoriteKeyword).where(
            UserFavoriteKeyword.user_id == current_user.id,
            UserFavoriteKeyword.keyword == keyword,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "FAVORITE_NOT_FOUND",
                "message": f"keyword '{keyword}' is not in favourites",
                "status": 404,
            },
        )
    db.delete(row)
    db.commit()
