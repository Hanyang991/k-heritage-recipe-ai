"""Heritage document — metadata for a record fetched from a public archive."""

import uuid

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    institution: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        doc="jangseogak / nfm / culture",
    )
    region: Mapped[str] = mapped_column(String(60), default="")
    period: Mapped[str] = mapped_column(
        String(60), default="", doc="조선전기 / 조선후기 / 근대 etc."
    )
    category: Mapped[str] = mapped_column(String(60), default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    original_text: Mapped[str] = mapped_column(Text, default="")
    modern_text: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")

    license: Mapped[str] = mapped_column(String(20), default="KOGL-1")
