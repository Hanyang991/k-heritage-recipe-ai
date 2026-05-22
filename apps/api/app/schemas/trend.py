"""Trend keyword schemas."""

from datetime import date

from pydantic import BaseModel, ConfigDict


class TrendOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rank: int
    keyword: str
    region: str
    change_percent: float
    is_up: bool
    week_of: date
