"""Weekly trend keyword snapshot."""

import uuid
from datetime import date

from sqlalchemy import Date, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Trend(Base, TimestampMixin):
    __tablename__ = "trends"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    keyword: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    region: Mapped[str] = mapped_column(String(60), default="전국", index=True)
    change_percent: Mapped[float] = mapped_column(Float, default=0.0)
    is_up: Mapped[bool] = mapped_column(default=True)
    week_of: Mapped[date] = mapped_column(Date, nullable=False, index=True)
