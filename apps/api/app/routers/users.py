"""Authenticated user profile + onboarding endpoint (spec §8.2.1)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserOut, UserUpdateRequest

router = APIRouter(prefix="/private/users", tags=["users"])


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserOut:
    """Partial update of the current user's profile.

    Used by the onboarding flow to record persona / preferred regions /
    preferred keywords, and to flip ``onboarding_completed`` once the user
    finishes (or explicitly skips) the wizard.
    """
    if payload.display_name is not None:
        # Don't blank out an existing display name with whitespace-only input.
        cleaned = payload.display_name.strip()
        if cleaned:
            current_user.display_name = cleaned
    if payload.persona is not None:
        current_user.persona = payload.persona.strip()
    if payload.preferred_regions is not None:
        current_user.preferred_regions = [r for r in payload.preferred_regions if r.strip()]
    if payload.preferred_keywords is not None:
        current_user.preferred_keywords = [k for k in payload.preferred_keywords if k.strip()]
    if payload.onboarding_completed is not None:
        current_user.onboarding_completed = payload.onboarding_completed
    db.commit()
    db.refresh(current_user)
    return UserOut.model_validate(current_user)
