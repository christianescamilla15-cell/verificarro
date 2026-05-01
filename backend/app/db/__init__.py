"""Database module for Verificarro.

SQLAlchemy 2.0 async + Alembic migrations. SQLite (aiosqlite) en dev
local Windows; Postgres (asyncpg) en Render. Switch vía `DATABASE_URL`.
"""

from app.db.base import Base
from app.db.session import (
    create_engine_for_url,
    get_async_session,
    get_engine,
    get_session_factory,
)

__all__ = [
    "Base",
    "create_engine_for_url",
    "get_async_session",
    "get_engine",
    "get_session_factory",
]
