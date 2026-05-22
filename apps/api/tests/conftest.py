"""Pytest fixtures — fresh SQLite DB per test, seeded with documents + trends."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Make sure config picks up a clean env before app modules import it
os.environ["JWT_SECRET_KEY"] = "test-secret-key-must-be-long-enough"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["HERITAGE_PROVIDER"] = "mock"
os.environ["PAYMENTS_PROVIDER"] = "mock"

# Use a single shared sqlite file for the whole test session so all
# sessions see the same data (in-memory dbs don't share between connections
# without StaticPool gymnastics, and a temp file is simpler).
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"

from app.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import create_app  # noqa: E402

# Reset settings cache so env vars are re-read
get_settings.cache_clear()  # type: ignore[attr-defined]


_engine = create_engine(
    os.environ["DATABASE_URL"], connect_args={"check_same_thread": False}, future=True
)
_TestSession = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)


def _override_get_db() -> Iterator:
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="session", autouse=True)
def _create_schema() -> Iterator[None]:
    Base.metadata.drop_all(bind=_engine)
    Base.metadata.create_all(bind=_engine)
    yield


@pytest.fixture()
def client() -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def db_session() -> Iterator:
    session = _TestSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    # Truncate all tables before each test for isolation.
    yield
    with _engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
