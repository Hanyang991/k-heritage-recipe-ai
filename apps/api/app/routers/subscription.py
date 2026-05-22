"""Subscription self-service endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.subscription import Plan
from app.models.user import User
from app.schemas.user import SubscriptionOut

router = APIRouter(prefix="/private/subscription", tags=["subscription"])


class PlanChangeRequest(BaseModel):
    plan: Plan


@router.get("", response_model=SubscriptionOut)
def get_my_subscription(
    current_user: User = Depends(get_current_user),
) -> SubscriptionOut:
    sub = current_user.subscription
    if sub is None:
        return SubscriptionOut(plan=Plan.FREE, monthly_recipe_count=0)
    return SubscriptionOut.model_validate(sub)


@router.post("/plan", response_model=SubscriptionOut)
def change_plan(
    payload: PlanChangeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    """Demo-only direct plan change. Production flow uses TossPayments billing."""
    sub = current_user.subscription
    if sub is None:
        from app.models.subscription import Subscription

        sub = Subscription(user_id=current_user.id, plan=payload.plan)
        db.add(sub)
    else:
        sub.plan = payload.plan
    db.commit()
    db.refresh(sub)
    return SubscriptionOut.model_validate(sub)
