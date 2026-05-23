"""Regression test — seeded demo & admin accounts must pass the login schema.

`pydantic.EmailStr` rejects reserved TLDs (e.g. `.local`, `.test`, `.invalid`).
Because the seed inserts users via the ORM, a reserved TLD slips into the DB
but then the same row can never be authenticated via `/v1/auth/login` (the
request schema rejects the email with a 422 before the password is even
checked). This test wires the seed into the API and asserts a real login
round-trip succeeds, so future seed changes can't silently break the demo.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.seed import (
    _ADMIN_USER_EMAIL,
    _ADMIN_USER_PASSWORD,
    _DEMO_USER_EMAIL,
    _DEMO_USER_PASSWORD,
    seed_users,
)


def test_seeded_demo_user_can_log_in(client: TestClient, db_session: Session) -> None:
    seed_users(db_session)

    r = client.post(
        "/v1/auth/login",
        json={"email": _DEMO_USER_EMAIL, "password": _DEMO_USER_PASSWORD},
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


def test_seeded_admin_user_can_log_in(client: TestClient, db_session: Session) -> None:
    seed_users(db_session)

    r = client.post(
        "/v1/auth/login",
        json={"email": _ADMIN_USER_EMAIL, "password": _ADMIN_USER_PASSWORD},
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]
