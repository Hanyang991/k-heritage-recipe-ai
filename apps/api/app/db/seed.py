"""Seed script — populates the dev DB with sample data.

Usage:
    python -m app.db.seed
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.auth.password import hash_password
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.document import Document
from app.models.subscription import Plan, Subscription
from app.models.trend import Trend
from app.models.user import User, UserRole
from app.services.heritage.mock import MockHeritageAdapter

logger = logging.getLogger(__name__)

# NB: domain must NOT be a reserved TLD (e.g. .local / .test / .invalid),
# otherwise pydantic's EmailStr blocks the seeded accounts from ever logging in.
_DEMO_USER_EMAIL = "demo@k-heritage.app"
_DEMO_USER_PASSWORD = "demo1234"
_ADMIN_USER_EMAIL = "admin@k-heritage.app"
_ADMIN_USER_PASSWORD = "admin1234"


def seed_documents(db: Session) -> None:
    if db.query(Document).count() > 0:
        logger.info("documents already seeded; skipping")
        return
    heritage = MockHeritageAdapter()
    for hd in heritage.list_seeded():
        db.add(
            Document(
                title=hd.title,
                institution=hd.institution,
                region=hd.region,
                period=hd.period,
                category=hd.category,
                year=hd.year,
                original_text=hd.original_text,
                summary=hd.summary,
                license=hd.license,
            )
        )
    db.commit()
    logger.info("seeded documents")


def seed_trends(db: Session) -> None:
    """Populate this week's trend snapshot via the configured discovery source.

    Mock provider (dev/CI) is deterministic per-keyword so the dashboard boots
    with a stable but discovery-shaped Top 20 from the ~80-keyword candidate
    pool — no hardcoded list to fall out of sync with the live path.
    """
    if db.query(Trend).count() > 0:
        logger.info("trends already seeded; skipping")
        return
    from app.jobs.refresh_trends import refresh_trends
    from app.services.trends import TrendsAdapterError

    try:
        result = refresh_trends(db)
        logger.info("seeded trends via discovery: %s", result)
    except TrendsAdapterError as exc:
        logger.warning("seed trends skipped (adapter error): %s", exc)


def seed_users(db: Session) -> None:
    if db.query(User).filter(User.email == _DEMO_USER_EMAIL).count() == 0:
        demo = User(
            email=_DEMO_USER_EMAIL,
            hashed_password=hash_password(_DEMO_USER_PASSWORD),
            display_name="Demo",
            role=UserRole.USER,
            onboarding_completed=True,
            persona="카페 사장",
            preferred_regions=["전국", "전라북도"],
            preferred_keywords=["쑥라떼", "오미자에이드"],
        )
        demo.subscription = Subscription(plan=Plan.FREE)
        db.add(demo)

    if db.query(User).filter(User.email == _ADMIN_USER_EMAIL).count() == 0:
        admin = User(
            email=_ADMIN_USER_EMAIL,
            hashed_password=hash_password(_ADMIN_USER_PASSWORD),
            display_name="Admin",
            role=UserRole.ADMIN,
            onboarding_completed=True,
        )
        admin.subscription = Subscription(plan=Plan.PRO)
        db.add(admin)

    db.commit()
    logger.info("seeded users")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_documents(db)
        seed_trends(db)
        seed_users(db)
        logger.info("Demo account: %s / %s", _DEMO_USER_EMAIL, _DEMO_USER_PASSWORD)
        logger.info("Admin account: %s / %s", _ADMIN_USER_EMAIL, _ADMIN_USER_PASSWORD)
    finally:
        db.close()


if __name__ == "__main__":
    main()
