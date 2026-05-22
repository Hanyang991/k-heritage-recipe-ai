"""Subscription model — plan + TossPayments billing key state."""

import enum
import uuid
from datetime import date

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Plan(str, enum.Enum):
    FREE = "free"
    PRO = "pro"
    B2B = "b2b"


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, unique=True, index=True
    )

    plan: Mapped[Plan] = mapped_column(Enum(Plan), default=Plan.FREE, nullable=False)

    # Free plan usage counters (reset monthly by background job)
    monthly_recipe_count: Mapped[int] = mapped_column(Integer, default=0)

    # TossPayments fields (spec section 12.5)
    billing_key: Mapped[str] = mapped_column(String(255), default="")
    toss_customer_key: Mapped[str] = mapped_column(String(100), default="")
    next_billing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_payment_status: Mapped[str] = mapped_column(String(20), default="")
    last_payment_at = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="subscription")
