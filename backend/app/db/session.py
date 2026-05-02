"""Engine + session factory + FastAPI dependency.

Engine global lazy-initialized para que tests puedan resetear la DB
entre runs vía `engine.dispose() + create_all`.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine_for_url(url: str, *, echo: bool = False) -> AsyncEngine:
    """Crea un engine async para `url`. Útil para tests."""
    return create_async_engine(url, echo=echo, future=True)


def get_engine() -> AsyncEngine:
    """Devuelve el engine global (creado on-demand desde settings).

    Usa `database_url_async` que normaliza el driver — `postgres://`
    de Render se traduce a `postgresql+asyncpg://` automáticamente.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine_for_url(
            settings.database_url_async, echo=settings.env == "development"
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Devuelve la session factory global."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _session_factory


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields an `AsyncSession` con commit/rollback."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def reset_engine_for_tests() -> None:
    """Util para tests: limpia el singleton para que el siguiente test
    obtenga un engine nuevo (útil al cambiar `DATABASE_URL`)."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


def _set_engine_for_tests(engine, factory) -> None:
    """Inyecta un engine + factory específicos en el singleton global.

    Útil para tests que llaman directamente a funciones que internamente
    usan `get_session_factory()` (e.g. `recover_orphan_paid_payments`)
    pero el test ya creó su propio engine in-memory aislado. Sin esto,
    el código bajo test crearía un segundo engine apuntando al
    `DATABASE_URL` del entorno (o el SQLite local file) y los seeds
    del test no aparecerían.

    Llamar `reset_engine_for_tests()` en teardown para limpiar.
    """
    global _engine, _session_factory
    _engine = engine
    _session_factory = factory


SessionDep = Annotated[AsyncSession, Depends(get_async_session)]
