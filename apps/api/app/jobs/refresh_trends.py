"""Refresh the weekly trend snapshot via the configured discovery source.

Calls ``TrendKeywordDiscovery`` (default ``CuratedWatchlistDiscovery`` over
``DEFAULT_WATCHLIST``) to rank the candidate pool and writes the top-N into
the ``trends`` table:

- ``rank`` is assigned by the discovery's score (blended popularity + rise),
  not raw current ratio. This is what makes the dashboard's "급상승" label
  honest: a stable-but-popular keyword and a small-but-spiking one get
  balanced consideration.
- ``change_percent`` is the week-over-week % change carried over from the
  discovery output. ``is_up`` is ``True`` iff that change is ``>= 0``.
- Rows for the same ``(keyword, region, week_of)`` are updated in place;
  rows for keywords that fell out of the top-N stay in the table (history).

Usage
-----
::

    # ad-hoc run with whatever discovery+adapter is configured
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
from app.services.trends import (
    CuratedWatchlistDiscovery,
    TrendKeywordDiscovery,
    TrendsAdapter,
    get_trend_discovery,
    get_trends_adapter,
)
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
    top_n: int = 20,
    region: str = "전국",
    adapter: TrendsAdapter | None = None,
    discovery: TrendKeywordDiscovery | None = None,
    today: date | None = None,
) -> RefreshResult:
    """Discover the top-N trending keywords and upsert one ``Trend`` row each.

    ``adapter`` is a convenience: if you pass an adapter and no ``discovery``,
    the function builds a ``CuratedWatchlistDiscovery`` around it. Explicit
    ``discovery`` always wins. Passing ``watchlist`` only takes effect when
    discovery is built from adapter — explicit ``discovery`` already carries
    its own candidate pool.
    """
    end = today or date.today()
    week_of = end - timedelta(days=end.weekday())  # Monday of `end`'s week

    if discovery is None:
        if adapter is not None:
            candidates = watchlist if watchlist is not None else DEFAULT_WATCHLIST
            discovery = CuratedWatchlistDiscovery(adapter, candidates, weeks=weeks)
        else:
            discovery = get_trend_discovery()
            # Re-build with overridden watchlist if the caller asked for one.
            if watchlist is not None:
                discovery = CuratedWatchlistDiscovery(get_trends_adapter(), watchlist, weeks=weeks)

    discovered = discovery.discover(today=end, limit=top_n)
    if not discovered:
        logger.info("discovery returned no candidates — skipping refresh")
        return RefreshResult(week_of=None, inserted=0, updated=0)

    inserted = 0
    updated = 0
    for rank, d in enumerate(discovered, start=1):
        change_pct = round(d.rise_percent if d.rise_percent is not None else 0.0, 2)
        is_up = change_pct >= 0
        existing = (
            db.query(Trend)
            .filter(
                Trend.keyword == d.keyword,
                Trend.region == region,
                Trend.week_of == week_of,
            )
            .one_or_none()
        )
        if existing is None:
            db.add(
                Trend(
                    id=str(uuid.uuid4()),
                    keyword=d.keyword,
                    rank=rank,
                    region=region,
                    change_percent=change_pct,
                    is_up=is_up,
                    week_of=week_of,
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
        week_of,
        inserted,
        updated,
    )
    return RefreshResult(week_of=week_of, inserted=inserted, updated=updated)


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
