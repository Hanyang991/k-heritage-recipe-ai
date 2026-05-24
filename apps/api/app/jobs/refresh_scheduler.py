"""Daily scheduler that runs ``refresh_trends`` once per day.

Operational rationale
---------------------
With ``TRENDS_DISCOVERY_SOURCE=open`` + ``TRENDS_PROVIDER=live`` enabled
(PR #11–#18), the trend snapshot in the ``trends`` table needs to be
refreshed on a regular cadence. A sync refresh during an HTTP request is
too slow (Gemini alone is ~10–15s, Naver DataLab another 5–30s with all
chunks). The right pattern is a daily background job.

This module is intentionally minimal: no APScheduler, no Celery, no
external cron — just a Python loop that sleeps until the next scheduled
hour (UTC) and runs the refresh. It runs as its own ``docker-compose``
service so it has its own process lifecycle, restart policy, and logs.

Operators who already have a scheduler (Kubernetes ``CronJob``, host
cron, GitHub Actions schedule, AWS EventBridge) can ignore this script
and call ``python -m app.jobs.refresh_trends`` directly on their own
cadence.

Configuration
-------------
``TRENDS_REFRESH_HOUR_UTC`` (default 18, i.e. 18:00 UTC = 03:00 KST):
The hour-of-day at which the scheduler triggers a refresh. We pick
03 KST so that by the time East Asian users open the dashboard in the
morning, the new top-N is already populated. Operators outside Korea
can override.

Resilience
----------
Each iteration's refresh is wrapped in a try/except. A failure logs an
ERROR and lets the scheduler sleep until the *next* scheduled tick — we
don't retry within the same day because Naver DataLab and Gemini both
have per-day quotas and an uncontrolled retry could burn through them.
"""

from __future__ import annotations

import logging
import signal
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.config import get_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.jobs.refresh_trends import refresh_trends

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _next_run_at(now: datetime, hour_utc: int) -> datetime:
    """Compute the next UTC datetime at which the refresh should run."""
    if not 0 <= hour_utc <= 23:
        raise ValueError(f"hour_utc must be 0..23, got {hour_utc}")
    candidate = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _sleep_until(
    target: datetime,
    *,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = _utc_now,
) -> None:
    """Sleep in 60s ticks so SIGTERM is observed within at most a minute."""
    while True:
        remaining = (target - now()).total_seconds()
        if remaining <= 0:
            return
        sleep(min(60.0, remaining))


def _run_once() -> None:
    db = SessionLocal()
    try:
        result = refresh_trends(db)
        logger.info(
            "refresh_scheduler: week_of=%s inserted=%d updated=%d",
            result.week_of,
            result.inserted,
            result.updated,
        )
    finally:
        db.close()


_stop_requested = False


def _handle_sigterm(_signum: int, _frame: object) -> None:
    global _stop_requested
    logger.info("refresh_scheduler: SIGTERM received, will exit after current sleep tick")
    _stop_requested = True


def run_forever(*, hour_utc: int | None = None) -> None:
    """Loop: sleep to next scheduled hour, run refresh, repeat.

    Returns only on SIGTERM/SIGINT (the docker-compose ``stop`` path).
    """
    settings = get_settings()
    target_hour = hour_utc if hour_utc is not None else settings.trends_refresh_hour_utc
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)
    Base.metadata.create_all(bind=engine)

    logger.info(
        "refresh_scheduler: starting (target hour %02d:00 UTC, discovery=%s, provider=%s)",
        target_hour,
        settings.trends_discovery_source,
        settings.trends_provider,
    )

    while not _stop_requested:
        next_at = _next_run_at(_utc_now(), target_hour)
        logger.info("refresh_scheduler: next refresh at %s UTC", next_at.isoformat())
        _sleep_until(next_at)
        if _stop_requested:
            break
        try:
            _run_once()
        except Exception:  # noqa: BLE001 — daily job must not crash the loop
            logger.exception("refresh_scheduler: refresh failed; will retry at the next tick")

    logger.info("refresh_scheduler: exited cleanly")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run_forever()


if __name__ == "__main__":
    main()
