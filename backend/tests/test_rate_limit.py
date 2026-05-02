"""Tests del rate limiter slowapi (MOD-004).

Por default, conftest.py deshabilita el limiter para todos los tests.
Los tests aquí usan el fixture `enable_rate_limit` para activarlo solo
en su scope y validar que el sistema responde 429 cuando se excede.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import get_async_session
from app.main import app


@pytest_asyncio.fixture
async def db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def client(db_factory):
    async def override_session():
        async with db_factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_async_session] = override_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_request_link_rate_limit_blocks_after_5(
    client, enable_rate_limit,
) -> None:
    """`/api/auth/request-link` permite 5/min, el 6to debe ser 429."""
    with patch("app.api.auth.send_magic_link_email", autospec=True):
        responses = [
            client.post(
                "/api/auth/request-link",
                json={"email": f"user{i}@example.com"},
            )
            for i in range(7)
        ]

    statuses = [r.status_code for r in responses]
    # Primeros 5 OK (200), luego 429
    assert statuses[:5] == [200, 200, 200, 200, 200]
    assert 429 in statuses[5:], f"esperaba 429 después del 5to, got {statuses}"


def test_rate_limit_response_is_spanish_with_retry_after(
    client, enable_rate_limit,
) -> None:
    """El handler custom devuelve mensaje en español MX + retry_after."""
    with patch("app.api.auth.send_magic_link_email", autospec=True):
        for _ in range(5):
            client.post(
                "/api/auth/request-link",
                json={"email": "spam@example.com"},
            )
        # 6to request → 429
        res = client.post(
            "/api/auth/request-link",
            json={"email": "spam@example.com"},
        )
    assert res.status_code == 429
    body = res.json()
    assert "Demasiadas requests" in body["detail"]
    assert "retry_after_seconds" in body


def test_health_endpoint_not_rate_limited(client, enable_rate_limit) -> None:
    """`/health` NO tiene @limiter.limit — debe responder OK indefinidamente."""
    statuses = [client.get("/health").status_code for _ in range(20)]
    assert all(s == 200 for s in statuses)
