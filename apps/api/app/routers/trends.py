"""Trend dashboard endpoint (spec FR-02)."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.trend import Trend
from app.schemas.trend import TrendOut, TrendSeriesOut, TrendSeriesPoint
from app.services.trends import TrendsAdapterError, get_trends_adapter

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


@router.get("/series", response_model=TrendSeriesOut)
def get_trend_series(
    keyword: str = Query(..., min_length=1, max_length=64),
    weeks: int = Query(8, ge=2, le=52),
) -> TrendSeriesOut:
    """Return a weekly time-series for a single keyword via the configured adapter.

    Pulled on-demand (not persisted) so the chart reflects whatever the
    upstream provider (mock or Naver DataLab) currently reports for the
    given lookback window. The dashboard uses this for a per-keyword
    drill-down chart.
    """
    end = date.today()
    start = end - timedelta(weeks=weeks)
    try:
        adapter = get_trends_adapter()
        series = adapter.fetch_series([keyword], start, end, "week")
    except TrendsAdapterError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "TRENDS_UPSTREAM_ERROR",
                "message": str(exc),
                "status": 502,
            },
        ) from exc

    if not series:
        return TrendSeriesOut(keyword=keyword, time_unit="week", points=[])

    matched = next((s for s in series if s.keyword == keyword), series[0])
    points = [
        TrendSeriesPoint(period=p.period, ratio=p.ratio)
        for p in sorted(matched.data, key=lambda p: p.period)
    ]
    return TrendSeriesOut(keyword=keyword, time_unit="week", points=points)
