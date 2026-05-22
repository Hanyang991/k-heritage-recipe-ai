"""Trend dashboard tests."""

import uuid
from datetime import date

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.models.trend import Trend


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
