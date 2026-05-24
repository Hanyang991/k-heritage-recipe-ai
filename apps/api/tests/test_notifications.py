"""Tests for the notifications router + the favorite-keyword detector."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.favorite_keyword import UserFavoriteKeyword
from app.models.notification import Notification
from app.models.trend import Trend
from app.services.notifications import detect_favorite_keyword_notifications


def _register(client: TestClient, email: str = "notif@example.org") -> tuple[str, str]:
    r = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "secret123"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    return token, me.json()["id"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_trend(
    keyword: str,
    *,
    rank: int,
    week_of: date,
    change_percent: float = 0.0,
    region: str = "전국",
) -> Trend:
    return Trend(
        id=str(uuid.uuid4()),
        keyword=keyword,
        rank=rank,
        region=region,
        change_percent=change_percent,
        is_up=change_percent >= 0,
        week_of=week_of,
    )


def test_list_starts_empty(client: TestClient) -> None:
    token, _ = _register(client)
    r = client.get("/v1/private/me/notifications", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body == {"items": [], "unread_count": 0}


def test_detector_emits_for_newly_entered_favorite(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client)
    week_of = date(2024, 1, 1)  # a Monday
    # Star a keyword …
    db_session.add(UserFavoriteKeyword(user_id=user_id, keyword="두바이쫀득쿠키"))
    # … that newly enters the top-N this week (no previous_week row).
    db_session.add(_make_trend("두바이쫀득쿠키", rank=3, week_of=week_of, change_percent=8.0))
    db_session.commit()

    inserted = detect_favorite_keyword_notifications(db_session, week_of=week_of)
    assert inserted == 1

    listing = client.get("/v1/private/me/notifications", headers=_auth(token)).json()
    assert listing["unread_count"] == 1
    [item] = listing["items"]
    assert item["type"] == "favorite_keyword_trending"
    assert item["payload"]["keyword"] == "두바이쫀득쿠키"
    assert item["payload"]["rank"] == 3
    assert item["payload"]["previous_rank"] is None
    assert item["payload"]["week_of"] == "2024-01-01"
    assert item["read_at"] is None


def test_detector_emits_for_big_change_percent(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client)
    week_of = date(2024, 1, 8)
    previous_week = week_of - timedelta(days=7)
    db_session.add(UserFavoriteKeyword(user_id=user_id, keyword="약과"))
    # Stable rank but a +25% change — qualifies as "rise".
    db_session.add(_make_trend("약과", rank=10, week_of=previous_week, change_percent=2.0))
    db_session.add(_make_trend("약과", rank=10, week_of=week_of, change_percent=25.0))
    db_session.commit()

    inserted = detect_favorite_keyword_notifications(db_session, week_of=week_of)
    assert inserted == 1

    listing = client.get("/v1/private/me/notifications", headers=_auth(token)).json()
    [item] = listing["items"]
    assert item["payload"]["change_percent"] == 25.0


def test_detector_emits_for_big_rank_jump(client: TestClient, db_session: Session) -> None:
    _token, user_id = _register(client)
    week_of = date(2024, 1, 15)
    previous_week = week_of - timedelta(days=7)
    db_session.add(UserFavoriteKeyword(user_id=user_id, keyword="흑임자"))
    # Tiny change_percent but a 12-rank jump — qualifies on rank delta alone.
    db_session.add(_make_trend("흑임자", rank=18, week_of=previous_week, change_percent=1.0))
    db_session.add(_make_trend("흑임자", rank=6, week_of=week_of, change_percent=3.0))
    db_session.commit()

    inserted = detect_favorite_keyword_notifications(db_session, week_of=week_of)
    assert inserted == 1


def test_detector_skips_stable_favorites(client: TestClient, db_session: Session) -> None:
    """No rank jump, no big change → no notification."""
    _token, user_id = _register(client)
    week_of = date(2024, 1, 22)
    previous_week = week_of - timedelta(days=7)
    db_session.add(UserFavoriteKeyword(user_id=user_id, keyword="식혜"))
    db_session.add(_make_trend("식혜", rank=12, week_of=previous_week, change_percent=2.0))
    db_session.add(_make_trend("식혜", rank=11, week_of=week_of, change_percent=3.0))
    db_session.commit()

    inserted = detect_favorite_keyword_notifications(db_session, week_of=week_of)
    assert inserted == 0


def test_detector_is_idempotent_per_week(client: TestClient, db_session: Session) -> None:
    """Running the detector twice on the same week does not duplicate rows."""
    _token, user_id = _register(client)
    week_of = date(2024, 2, 5)
    db_session.add(UserFavoriteKeyword(user_id=user_id, keyword="두바이쫀득쿠키"))
    db_session.add(_make_trend("두바이쫀득쿠키", rank=3, week_of=week_of, change_percent=8.0))
    db_session.commit()

    inserted_first = detect_favorite_keyword_notifications(db_session, week_of=week_of)
    inserted_second = detect_favorite_keyword_notifications(db_session, week_of=week_of)
    assert inserted_first == 1
    assert inserted_second == 0
    count = db_session.query(Notification).count()
    assert count == 1


def test_detector_is_per_user(client: TestClient, db_session: Session) -> None:
    """User A's favourite generates a notification for A, not for B."""
    token_a, user_a = _register(client, email="a@example.org")
    token_b, _user_b = _register(client, email="b@example.org")
    week_of = date(2024, 2, 12)
    db_session.add(UserFavoriteKeyword(user_id=user_a, keyword="두바이쫀득쿠키"))
    db_session.add(_make_trend("두바이쫀득쿠키", rank=2, week_of=week_of, change_percent=12.0))
    db_session.commit()

    detect_favorite_keyword_notifications(db_session, week_of=week_of)
    a_listing = client.get("/v1/private/me/notifications", headers=_auth(token_a)).json()
    b_listing = client.get("/v1/private/me/notifications", headers=_auth(token_b)).json()
    assert a_listing["unread_count"] == 1
    assert b_listing["unread_count"] == 0


def test_mark_read(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client)
    week_of = date(2024, 2, 19)
    db_session.add(UserFavoriteKeyword(user_id=user_id, keyword="약과"))
    db_session.add(_make_trend("약과", rank=4, week_of=week_of, change_percent=22.0))
    db_session.commit()
    detect_favorite_keyword_notifications(db_session, week_of=week_of)

    listing = client.get("/v1/private/me/notifications", headers=_auth(token)).json()
    notif_id = listing["items"][0]["id"]

    r = client.post(
        f"/v1/private/me/notifications/{notif_id}/read",
        headers=_auth(token),
    )
    assert r.status_code == 200
    assert r.json()["read_at"] is not None

    after = client.get("/v1/private/me/notifications", headers=_auth(token)).json()
    assert after["unread_count"] == 0
    assert after["items"][0]["read_at"] is not None


def test_mark_read_unknown_returns_404(client: TestClient) -> None:
    token, _ = _register(client)
    r = client.post(
        "/v1/private/me/notifications/does-not-exist/read",
        headers=_auth(token),
    )
    assert r.status_code == 404
    assert r.json()["error"] == "NOTIFICATION_NOT_FOUND"


def test_mark_read_other_users_notification_returns_404(
    client: TestClient, db_session: Session
) -> None:
    """User B cannot mark User A's notification as read (or even confirm it exists)."""
    token_a, user_a = _register(client, email="a@example.org")
    token_b, _user_b = _register(client, email="b@example.org")
    week_of = date(2024, 2, 26)
    db_session.add(UserFavoriteKeyword(user_id=user_a, keyword="약과"))
    db_session.add(_make_trend("약과", rank=4, week_of=week_of, change_percent=30.0))
    db_session.commit()
    detect_favorite_keyword_notifications(db_session, week_of=week_of)

    a_listing = client.get("/v1/private/me/notifications", headers=_auth(token_a)).json()
    notif_id = a_listing["items"][0]["id"]

    r = client.post(
        f"/v1/private/me/notifications/{notif_id}/read",
        headers=_auth(token_b),
    )
    assert r.status_code == 404


def test_mark_all_read(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client)
    week_of = date(2024, 3, 4)
    db_session.add(UserFavoriteKeyword(user_id=user_id, keyword="약과"))
    db_session.add(UserFavoriteKeyword(user_id=user_id, keyword="식혜"))
    db_session.add(_make_trend("약과", rank=4, week_of=week_of, change_percent=22.0))
    db_session.add(_make_trend("식혜", rank=6, week_of=week_of, change_percent=21.0))
    db_session.commit()
    detect_favorite_keyword_notifications(db_session, week_of=week_of)

    r = client.post("/v1/private/me/notifications/read-all", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["marked_read"] == 2

    after = client.get("/v1/private/me/notifications", headers=_auth(token)).json()
    assert after["unread_count"] == 0
    # Running read-all a second time is a no-op (0 marked).
    second = client.post("/v1/private/me/notifications/read-all", headers=_auth(token)).json()
    assert second["marked_read"] == 0


def test_unread_only_filter(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client)
    week_of = date(2024, 3, 11)
    db_session.add(UserFavoriteKeyword(user_id=user_id, keyword="약과"))
    db_session.add(UserFavoriteKeyword(user_id=user_id, keyword="식혜"))
    db_session.add(_make_trend("약과", rank=4, week_of=week_of, change_percent=22.0))
    db_session.add(_make_trend("식혜", rank=6, week_of=week_of, change_percent=21.0))
    db_session.commit()
    detect_favorite_keyword_notifications(db_session, week_of=week_of)

    listing = client.get("/v1/private/me/notifications", headers=_auth(token)).json()
    first_id = listing["items"][0]["id"]
    client.post(f"/v1/private/me/notifications/{first_id}/read", headers=_auth(token))

    unread = client.get(
        "/v1/private/me/notifications?unread_only=true", headers=_auth(token)
    ).json()
    assert len(unread["items"]) == 1
    assert unread["unread_count"] == 1


def test_anonymous_access_is_rejected(client: TestClient) -> None:
    r = client.get("/v1/private/me/notifications")
    assert r.status_code == 401
