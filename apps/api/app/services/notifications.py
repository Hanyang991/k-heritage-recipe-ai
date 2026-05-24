"""Background detectors that turn data-state changes into ``Notification`` rows.

The current set of detectors:

* :func:`detect_favorite_keyword_notifications` — when the weekly trend
  snapshot is refreshed, find each user's favourite keywords and emit a
  notification if the keyword either newly entered the top-N or rose
  significantly (``CHANGE_PERCENT_THRESHOLD``) versus last week.

Detectors are written to be **idempotent per (user, keyword, week_of)** —
re-running the same refresh on the same week does not produce duplicates.
This keeps the integration with ``refresh_trends`` simple (just call the
detector after committing the snapshot, no need to gate on "is this the
first run today").
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.favorite_keyword import UserFavoriteKeyword
from app.models.notification import Notification, NotificationType
from app.models.trend import Trend

logger = logging.getLogger(__name__)


CHANGE_PERCENT_THRESHOLD = 20.0
"""Minimum week-over-week % change to emit a notification for an existing trend.

A favourite keyword that goes from rank 14 with +5% to rank 14 with +6% is
not interesting; one that jumps to +25% is. This threshold is intentionally
generous — the user opted in to this keyword, so a moderate move is signal,
not noise.
"""


def detect_favorite_keyword_notifications(
    db: Session,
    *,
    week_of: date,
    region: str = "전국",
) -> int:
    """Emit notifications for favourites whose ranking moved this week.

    Returns the number of notifications inserted.

    A notification is emitted when *any* of:

    * the keyword newly entered the top-N this week (``previous_rank=None``);
    * the keyword's ``change_percent`` for this week is ``>= 20%`` (rise);
    * the keyword moved up by at least 5 ranks since last week.

    For each ``(user, keyword, week_of)`` only one notification row is ever
    written — re-running the detector on the same week is a no-op.
    """
    favourites: Sequence[UserFavoriteKeyword] = (
        db.execute(select(UserFavoriteKeyword)).scalars().all()
    )
    if not favourites:
        return 0

    previous_week = week_of - timedelta(days=7)

    favourite_keywords = sorted({f.keyword for f in favourites})
    current_rows: dict[str, Trend] = {
        t.keyword: t
        for t in db.execute(
            select(Trend).where(
                Trend.week_of == week_of,
                Trend.region == region,
                Trend.keyword.in_(favourite_keywords),
            )
        )
        .scalars()
        .all()
    }
    previous_rows: dict[str, Trend] = {
        t.keyword: t
        for t in db.execute(
            select(Trend).where(
                Trend.week_of == previous_week,
                Trend.region == region,
                Trend.keyword.in_(favourite_keywords),
            )
        )
        .scalars()
        .all()
    }

    # Pull existing notifications for this week so we can dedupe.
    existing_keys: set[tuple[str, str]] = set()
    existing = (
        db.execute(
            select(Notification).where(
                Notification.type == NotificationType.FAVORITE_KEYWORD_TRENDING,
            )
        )
        .scalars()
        .all()
    )
    week_of_iso = week_of.isoformat()
    for row in existing:
        payload = row.payload or {}
        if payload.get("week_of") == week_of_iso:
            existing_keys.add((row.user_id, payload.get("keyword", "")))

    inserted = 0
    for fav in favourites:
        current = current_rows.get(fav.keyword)
        if current is None:
            # Favourite didn't make the top-N this week — nothing interesting.
            continue
        previous = previous_rows.get(fav.keyword)
        prev_rank = previous.rank if previous is not None else None
        rank_jump = (prev_rank - current.rank) if prev_rank is not None else None

        is_newly_entered = prev_rank is None
        is_big_rise = current.change_percent >= CHANGE_PERCENT_THRESHOLD
        is_rank_jump = rank_jump is not None and rank_jump >= 5

        if not (is_newly_entered or is_big_rise or is_rank_jump):
            continue
        if (fav.user_id, fav.keyword) in existing_keys:
            continue

        db.add(
            Notification(
                user_id=fav.user_id,
                type=NotificationType.FAVORITE_KEYWORD_TRENDING,
                payload={
                    "keyword": fav.keyword,
                    "rank": current.rank,
                    "previous_rank": prev_rank,
                    "change_percent": current.change_percent,
                    "week_of": week_of_iso,
                },
            )
        )
        inserted += 1

    if inserted:
        db.commit()
        logger.info(
            "favorite-keyword notifications: week_of=%s inserted=%d",
            week_of,
            inserted,
        )
    return inserted
