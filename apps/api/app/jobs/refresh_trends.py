"""Refresh the weekly trend snapshot from the configured trends adapter.

Pulls a weekly time-series for the watchlist via ``TrendsAdapter`` and writes
the latest week into the ``trends`` table:

- ``rank`` is assigned by sorting the watchlist by the current week's ratio,
  descending.
- ``change_percent`` is the % change of ratio vs the previous week for the
  same keyword. ``is_up`` is True iff current >= previous.
- Existing rows for the same ``(keyword, region, week_of)`` are updated
  in place; missing rows are inserted.

Per-chunk normalization caveat
------------------------------
Naver DataLab caps a single request at 5 keywordGroups, so a 20-keyword
watchlist is split into 4 calls. Each call's ``ratio`` is normalized to its
own 100 = peak, which means cross-chunk ranks are an approximation. The
``change_percent`` metric (per-keyword, vs its own previous week) is
unaffected. A pivot-based cross-chunk normalization can be added later
without changing the persisted schema.

Usage
-----
::

    # ad-hoc run
    python -m app.jobs.refresh_trends

    # admin-triggered (see POST /v1/admin/trends/refresh)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.trend import Trend
from app.services.trends import TrendsAdapter, get_trends_adapter
from app.services.trends.watchlist import DEFAULT_WATCHLIST

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RefreshResult:
    week_of: date | None
    inserted: int
    updated: int


def refresh_trends(
    db: Session,
    *,
    watchlist: list[str] | None = None,
    weeks: int = 8,
    region: str = "전국",
    adapter: TrendsAdapter | None = None,
    today: date | None = None,
) -> RefreshResult:
    """Pull latest weekly series and upsert one ``Trend`` row per keyword."""
    watchlist = watchlist or DEFAULT_WATCHLIST
    adapter = adapter or get_trends_adapter()
    end = today or date.today()
    start = end - timedelta(weeks=weeks)

    series = adapter.fetch_series(watchlist, start, end, "week")
    if not series:
        logger.info("adapter returned no series — skipping refresh")
        return RefreshResult(week_of=None, inserted=0, updated=0)

    latest_period = max((p.period for s in series for p in s.data), default=None)
    if latest_period is None:
        logger.info("series have no datapoints — skipping refresh")
        return RefreshResult(week_of=None, inserted=0, updated=0)

    stats: list[tuple[str, float, float, bool]] = []
    for s in series:
        ordered = sorted(s.data, key=lambda p: p.period)
        if not ordered:
            continue
        current = ordered[-1].ratio
        previous = ordered[-2].ratio if len(ordered) >= 2 else current
        change_pct = ((current - previous) / previous * 100.0) if previous > 0 else 0.0
        stats.append((s.keyword, current, round(change_pct, 2), current >= previous))

    stats.sort(key=lambda t: -t[1])

    inserted = 0
    updated = 0
    for rank, (keyword, _current, change_pct, is_up) in enumerate(stats, start=1):
        existing = (
            db.query(Trend)
            .filter(
                Trend.keyword == keyword,
                Trend.region == region,
                Trend.week_of == latest_period,
            )
            .one_or_none()
        )
        if existing is None:
            db.add(
                Trend(
                    id=str(uuid.uuid4()),
                    keyword=keyword,
                    rank=rank,
                    region=region,
                    change_percent=change_pct,
                    is_up=is_up,
                    week_of=latest_period,
                )
            )
            inserted += 1
        else:
            existing.rank = rank
            existing.change_percent = change_pct
            existing.is_up = is_up
            updated += 1

    db.commit()
    logger.info(
        "refresh complete: week_of=%s inserted=%d updated=%d",
        latest_period,
        inserted,
        updated,
    )
    return RefreshResult(week_of=latest_period, inserted=inserted, updated=updated)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        refresh_trends(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
