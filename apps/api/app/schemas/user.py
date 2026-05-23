"""User-facing schemas."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.subscription import Plan
from app.models.user import UserRole


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plan: Plan
    monthly_recipe_count: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    display_name: str
    role: UserRole
    onboarding_completed: bool = False
    persona: str = ""
    preferred_regions: list[str] = Field(default_factory=list)
    preferred_keywords: list[str] = Field(default_factory=list)
    subscription: SubscriptionOut | None = None


class UserUpdateRequest(BaseModel):
    """Owner-editable profile fields used by the onboarding flow (spec §8.2.1).

    Every field is optional so the same endpoint can update any subset.
    """

    display_name: str | None = Field(default=None, max_length=120)
    persona: str | None = Field(default=None, max_length=60)
    preferred_regions: list[str] | None = Field(default=None, max_length=10)
    preferred_keywords: list[str] | None = Field(default=None, max_length=20)
    onboarding_completed: bool | None = None
