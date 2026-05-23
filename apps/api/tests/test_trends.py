"""Trend dashboard tests."""

import uuid
from datetime import date
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.models.trend import Trend
from app.services.trends import TrendsAdapterError
from app.services.trends.base import TrendDataPoint, TrendKeywordSeries


def _seed_trends(week_of: date) -> None:
    db = SessionLocal()
    try:
        for rank, kw in enumerate(["쑥라떼", "오미자에이드", "흑임자크림"], start=1):
            db.add(
                Trend(
                    id=str(uuid.uuid4()),
                    keyword=kw,
                    rank=rank,
                    region="전국",
                    change_percent=20.0 - rank,
                    is_up=True,
                    week_of=week_of,
                )
            )
        db.commit()
    finally:
        db.close()


def test_list_trends_returns_recent_week(client: TestClient) -> None:
    _seed_trends(date(2026, 5, 18))

    r = client.get("/v1/trends")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 3
    assert body[0]["rank"] == 1
    assert body[0]["keyword"] == "쑥라떼"


def test_empty_trends_returns_empty_list(client: TestClient) -> None:
    r = client.get("/v1/trends")
    assert r.status_code == 200
    assert r.json() == []


def _series(keyword: str, points: list[tuple[date, float]]) -> TrendKeywordSeries:
    return TrendKeywordSeries(
        keyword=keyword,
        data=tuple(TrendDataPoint(period=d, ratio=r) for d, r in points),
    )


class _FakeAdapter:
    def __init__(self, series: list[TrendKeywordSeries]) -> None:
        self._series = series
        self.calls: list[tuple[list[str], date, date, str]] = []

    def fetch_series(self, keywords, start, end, time_unit="week"):  # type: ignore[no-untyped-def]
        self.calls.append((list(keywords), start, end, time_unit))
        return list(self._series)


def test_trend_series_returns_weekly_points(client: TestClient) -> None:
    adapter = _FakeAdapter(
        [
            _series(
                "쑥라떼",
                [
                    (date(2025, 3, 17), 30.0),
                    (date(2025, 3, 24), 55.0),
                    (date(2025, 3, 31), 80.0),
                ],
            )
        ]
    )
    with patch("app.routers.trends.get_trends_adapter", return_value=adapter):
        r = client.get("/v1/trends/series", params={"keyword": "쑥라떼", "weeks": 4})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["keyword"] == "쑥라떼"
    assert body["time_unit"] == "week"
    assert body["points"] == [
        {"period": "2025-03-17", "ratio": 30.0},
        {"period": "2025-03-24", "ratio": 55.0},
        {"period": "2025-03-31", "ratio": 80.0},
    ]
    # Adapter should be called with exactly one keyword and time_unit=week.
    assert adapter.calls[0][0] == ["쑥라떼"]
    assert adapter.calls[0][3] == "week"


def test_trend_series_empty_when_adapter_returns_nothing(client: TestClient) -> None:
    with patch("app.routers.trends.get_trends_adapter", return_value=_FakeAdapter([])):
        r = client.get("/v1/trends/series", params={"keyword": "없는키워드"})
    assert r.status_code == 200
    assert r.json() == {"keyword": "없는키워드", "time_unit": "week", "points": []}


def test_trend_series_maps_upstream_error_to_502(client: TestClient) -> None:
    class _BoomAdapter:
        def fetch_series(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise TrendsAdapterError("Naver DataLab rejected credentials (401)")

    with patch("app.routers.trends.get_trends_adapter", return_value=_BoomAdapter()):
        r = client.get("/v1/trends/series", params={"keyword": "쑥라떼"})
    assert r.status_code == 502, r.text
    body = r.json()
    assert body["error"] == "TRENDS_UPSTREAM_ERROR"
    assert "Naver DataLab" in body["message"]


def test_trend_series_validates_weeks_bounds(client: TestClient) -> None:
    r = client.get("/v1/trends/series", params={"keyword": "쑥라떼", "weeks": 1})
    assert r.status_code == 422
    r = client.get("/v1/trends/series", params={"keyword": "쑥라떼", "weeks": 100})
    assert r.status_code == 422
