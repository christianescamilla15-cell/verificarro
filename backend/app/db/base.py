"""Declarative base para todos los modelos.

Patrón SQLAlchemy 2.0 con `DeclarativeBase` + tipado moderno
(`Mapped[T]` + `mapped_column`).
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base declarativa para todos los modelos."""


class TimestampMixin:
    """Mixin con `created_at` / `updated_at` automáticos."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        onupdate=_utc_now,
        nullable=False,
    )
