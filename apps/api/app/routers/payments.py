"""TossPayments billing endpoints (spec section 12).

These use the mock payments adapter by default. Webhook signature
verification is stubbed.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.subscription import Plan, Subscription
from app.models.user import User
from app.services.payments import get_payments_adapter

router = APIRouter(prefix="/payments", tags=["payments"])


class BillingConfirmRequest(BaseModel):
    auth_key: str
    customer_key: str


class PaymentsHistoryItem(BaseModel):
    amount_krw: int
    status: str
    occurred_at: str


@router.post("/billing/confirm")
def billing_confirm(
    payload: BillingConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    adapter = get_payments_adapter()
    result = adapter.confirm_billing(payload.auth_key, payload.customer_key)
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "BILLING_AUTH_FAILED",
                "message": result.message,
                "status": 402,
            },
        )
    sub = current_user.subscription
    if sub is None:
        sub = Subscription(user_id=current_user.id, plan=Plan.PRO)
        db.add(sub)
    sub.billing_key = result.billing_key
    sub.toss_customer_key = result.customer_key
    sub.plan = Plan.PRO
    db.commit()
    return {"plan": sub.plan.value, "billing_key_saved": True}


@router.delete("/billing/cancel")
def billing_cancel(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    adapter = get_payments_adapter()
    sub = current_user.subscription
    if sub is None or not sub.billing_key:
        return {"cancelled": False}
    adapter.cancel(sub.billing_key)
    sub.billing_key = ""
    sub.plan = Plan.FREE
    db.commit()
    return {"cancelled": True, "plan": sub.plan.value}


@router.post("/webhook")
def billing_webhook() -> dict:
    """Stub for TossPayments webhook. HMAC verification not implemented in mock mode."""
    return {"received": True}


@router.get("/history", response_model=list[PaymentsHistoryItem])
def payments_history(
    current_user: User = Depends(get_current_user),
) -> list[PaymentsHistoryItem]:
    # Mock mode: no history table yet, return empty list.
    _ = current_user
    return []
