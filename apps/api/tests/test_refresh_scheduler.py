"""Unit tests for ``app.jobs.refresh_scheduler`` — pure-logic only.

We test the scheduling primitives (``_next_run_at``, ``_sleep_until``) and
the exception-isolation of ``run_forever``. The actual refresh job is
patched out so the test suite never hits the database or external APIs
from this module.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.jobs.refresh_scheduler import _next_run_at, _sleep_until, run_forever

# ---------------------------------------------------------------------------
# _next_run_at
# ---------------------------------------------------------------------------


def test_next_run_at_returns_today_if_target_hour_is_in_the_future() -> None:
    now = datetime(2025, 5, 23, 10, 30, tzinfo=UTC)
    assert _next_run_at(now, hour_utc=18) == datetime(2025, 5, 23, 18, 0, tzinfo=UTC)


def test_next_run_at_returns_tomorrow_if_target_hour_already_passed() -> None:
    now = datetime(2025, 5, 23, 20, 0, tzinfo=UTC)
    assert _next_run_at(now, hour_utc=18) == datetime(2025, 5, 24, 18, 0, tzinfo=UTC)


def test_next_run_at_returns_tomorrow_when_called_exactly_at_target_hour() -> None:
    """Avoid infinite loop: equality bumps to next day."""
    now = datetime(2025, 5, 23, 18, 0, tzinfo=UTC)
    assert _next_run_at(now, hour_utc=18) == datetime(2025, 5, 24, 18, 0, tzinfo=UTC)


def test_next_run_at_handles_midnight_hour() -> None:
    now = datetime(2025, 5, 23, 23, 30, tzinfo=UTC)
    assert _next_run_at(now, hour_utc=0) == datetime(2025, 5, 24, 0, 0, tzinfo=UTC)


def test_next_run_at_rejects_invalid_hours() -> None:
    now = datetime(2025, 5, 23, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        _next_run_at(now, hour_utc=24)
    with pytest.raises(ValueError):
        _next_run_at(now, hour_utc=-1)


# ---------------------------------------------------------------------------
# _sleep_until — chunked sleep so SIGTERM is observable within ~60s
# ---------------------------------------------------------------------------


def test_sleep_until_chunks_into_60s_ticks() -> None:
    """A 5-minute target should produce 5 one-minute sleeps."""
    sleeps: list[float] = []
    start = datetime(2025, 5, 23, 10, 0, 0, tzinfo=UTC)
    target = start + timedelta(minutes=5)

    def fake_now() -> datetime:
        return start + timedelta(seconds=sum(sleeps))

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    _sleep_until(target, sleep=fake_sleep, now=fake_now)
    assert sleeps == [60.0, 60.0, 60.0, 60.0, 60.0]


def test_sleep_until_uses_partial_tick_when_less_than_a_minute_remaining() -> None:
    sleeps: list[float] = []
    start = datetime(2025, 5, 23, 10, 0, 0, tzinfo=UTC)
    target = start + timedelta(seconds=37)

    def fake_now() -> datetime:
        return start + timedelta(seconds=sum(sleeps))

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    _sleep_until(target, sleep=fake_sleep, now=fake_now)
    assert sleeps == [37.0]


def test_sleep_until_returns_immediately_when_target_already_passed() -> None:
    sleeps: list[float] = []
    start = datetime(2025, 5, 23, 10, 0, 0, tzinfo=UTC)
    target = start - timedelta(seconds=10)

    _sleep_until(target, sleep=lambda s: sleeps.append(s), now=lambda: start)
    assert sleeps == []


# ---------------------------------------------------------------------------
# run_forever — exception isolation per iteration
# ---------------------------------------------------------------------------


def test_run_forever_swallows_refresh_exception_and_continues() -> None:
    """A RuntimeError from _run_once must not kill the loop."""
    iterations = {"count": 0}

    def fake_sleep_until(_target: datetime) -> None:
        return None

    def fake_run_once() -> None:
        iterations["count"] += 1
        if iterations["count"] == 1:
            raise RuntimeError("naver datalab blew up")
        # Second call sets the stop flag so the loop exits.
        import app.jobs.refresh_scheduler as sched

        sched._stop_requested = True

    with (
        patch("app.jobs.refresh_scheduler._sleep_until", side_effect=fake_sleep_until),
        patch("app.jobs.refresh_scheduler._run_once", side_effect=fake_run_once),
        patch("app.jobs.refresh_scheduler.Base.metadata.create_all"),
        patch("app.jobs.refresh_scheduler.signal.signal"),
    ):
        import app.jobs.refresh_scheduler as sched

        sched._stop_requested = False
        try:
            run_forever(hour_utc=18)
        finally:
            sched._stop_requested = False
    assert iterations["count"] == 2  # error → next tick still ran


def test_run_forever_uses_settings_default_when_hour_not_passed() -> None:
    """Confirm the settings.trends_refresh_hour_utc default is plumbed through."""
    seen_hours: list[int] = []

    def fake_next_run_at(_now: datetime, hour_utc: int) -> datetime:
        seen_hours.append(hour_utc)
        import app.jobs.refresh_scheduler as sched

        sched._stop_requested = True
        return datetime.now(tz=UTC)

    with (
        patch("app.jobs.refresh_scheduler._next_run_at", side_effect=fake_next_run_at),
        patch("app.jobs.refresh_scheduler._sleep_until"),
        patch("app.jobs.refresh_scheduler.Base.metadata.create_all"),
        patch("app.jobs.refresh_scheduler.signal.signal"),
    ):
        import app.jobs.refresh_scheduler as sched

        sched._stop_requested = False
        try:
            run_forever()
        finally:
            sched._stop_requested = False
    # Default in app.config.Settings.trends_refresh_hour_utc is 18.
    assert seen_hours == [18]


def test_run_forever_honors_explicit_hour_override() -> None:
    seen_hours: list[int] = []

    def fake_next_run_at(_now: datetime, hour_utc: int) -> datetime:
        seen_hours.append(hour_utc)
        import app.jobs.refresh_scheduler as sched

        sched._stop_requested = True
        return datetime.now(tz=UTC)

    with (
        patch("app.jobs.refresh_scheduler._next_run_at", side_effect=fake_next_run_at),
        patch("app.jobs.refresh_scheduler._sleep_until"),
        patch("app.jobs.refresh_scheduler.Base.metadata.create_all"),
        patch("app.jobs.refresh_scheduler.signal.signal"),
    ):
        import app.jobs.refresh_scheduler as sched

        sched._stop_requested = False
        try:
            run_forever(hour_utc=7)
        finally:
            sched._stop_requested = False
    assert seen_hours == [7]
