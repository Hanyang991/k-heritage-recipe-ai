"""User-facing schemas."""

from pydantic import BaseModel, ConfigDict, EmailStr

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
    subscription: SubscriptionOut | None = None
