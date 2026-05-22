"""Trend dashboard endpoint (spec FR-02)."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.trend import Trend
from app.schemas.trend import TrendOut

router = APIRouter(prefix="/trends", tags=["trends"])


@router.get("", response_model=list[TrendOut])
def list_trends(region: str = "전국", db: Session = Depends(get_db)) -> list[TrendOut]:
    """Return the most recent week's trends, optionally filtered by region."""
    latest_week = db.query(Trend.week_of).order_by(Trend.week_of.desc()).limit(1).scalar()
    if latest_week is None:
        # Empty DB — return an empty list rather than 404 so the dashboard renders.
        return []
    query = db.query(Trend).filter(Trend.week_of == latest_week)
    if region and region != "전국":
        query = query.filter(Trend.region.in_([region, "전국"]))
    rows = query.order_by(Trend.rank.asc()).limit(20).all()
    return [TrendOut.model_validate(r) for r in rows]


@router.get("/weeks", response_model=list[date])
def list_weeks(db: Session = Depends(get_db)) -> list[date]:
    """Available weekly snapshots, newest first. Useful for an admin view."""
    cutoff = date.today() - timedelta(days=365)
    rows = (
        db.query(Trend.week_of)
        .filter(Trend.week_of >= cutoff)
        .distinct()
        .order_by(Trend.week_of.desc())
        .all()
    )
    return [row[0] for row in rows]
