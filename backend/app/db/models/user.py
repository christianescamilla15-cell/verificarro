"""Tabla `users`.

Esquema mínimo para D8: solo email + magic link state. Cuando D10
implemente magic link auth completa, los campos `magic_link_*` se
poblarán durante el flow de login.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    # Magic link auth state (D10)
    magic_link_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    magic_link_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_users_email_lower", "email"),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email}>"
