"""Seed script — populates the dev DB with sample data.

Usage:
    python -m app.db.seed
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta

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


_TOP_KEYWORDS = [
    ("쑥라떼", 32, True),
    ("오미자에이드", 28, True),
    ("흑임자크림", 19, True),
    ("매실청소다", 15, True),
    ("인절미케이크", 12, True),
    ("한방차라떼", 10, True),
    ("전통찻집", 8, True),
    ("곶감스무디", 7, True),
    ("유자청티", 5, True),
    ("대추차", 4, True),
    ("호박죽라떼", 3, True),
    ("미숫가루", 2, True),
    ("식혜빙수", 2, True),
    ("생강차", 1, True),
    ("수정과", 1, True),
    ("떡카페", 1, False),
    ("약과디저트", 2, False),
    ("전통병과", 3, False),
    ("한과세트", 4, False),
    ("옛날과자", 5, False),
]


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
    if db.query(Trend).count() > 0:
        logger.info("trends already seeded; skipping")
        return
    today = date.today()
    week_of = today - timedelta(days=today.weekday())  # Monday of this week
    for rank, (kw, change, is_up) in enumerate(_TOP_KEYWORDS, start=1):
        db.add(
            Trend(
                id=str(uuid.uuid4()),
                keyword=kw,
                rank=rank,
                region="전국",
                change_percent=float(change),
                is_up=is_up,
                week_of=week_of,
            )
        )
    db.commit()
    logger.info("seeded trends")


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
