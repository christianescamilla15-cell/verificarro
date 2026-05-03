"""Tests del endpoint /api/scan/precheck (TIER 3 auto-capture).

El precheck es una pasada barata con Haiku 4.5 que el frontend invoca
cuando sus heurísticas client-side detectan un frame "listo". Si Haiku
confirma que es plate/vin/invoice, el frontend dispara el smart_scan
completo. Si dice none/unclear, el watcher sigue mirando.

Tests cubren el endpoint + la función pura `precheck_image` con la
SDK de Anthropic mockeada.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import get_async_session
from app.main import app
from app.services.smart_scanner import (
    PrecheckResult,
    precheck_image,
)


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


# Fake image base64 — solo cualquier string >100 chars para pasar Pydantic
_TINY_IMG = "A" * 200


def _fake_anthropic_response(text: str):
    """Mock del shape que devuelve Anthropic SDK."""
    block = type("Block", (), {"type": "text", "text": text})()
    return type("Resp", (), {"content": [block]})()


# ---------------------------------------------------------------------------
# /api/scan/precheck endpoint


def test_precheck_returns_plate_when_haiku_says_plate(client) -> None:
    """Happy path — Haiku clasifica plate, endpoint devuelve plate."""
    with patch(
        "app.api.scan.precheck_image",
        new=AsyncMock(return_value=PrecheckResult(type="plate", raw="plate")),
    ):
        res = client.post(
            "/api/scan/precheck",
            json={"image_base64": _TINY_IMG, "media_type": "image/jpeg"},
        )
    assert res.status_code == 200
    assert res.json() == {"type": "plate"}


@pytest.mark.parametrize("haiku_type", ["plate", "vin", "invoice", "none", "unclear"])
def test_precheck_passes_through_all_valid_types(client, haiku_type) -> None:
    """Los 5 tipos válidos pasan por el endpoint sin transformación."""
    with patch(
        "app.api.scan.precheck_image",
        new=AsyncMock(return_value=PrecheckResult(type=haiku_type, raw=haiku_type)),
    ):
        res = client.post(
            "/api/scan/precheck",
            json={"image_base64": _TINY_IMG},
        )
    assert res.status_code == 200
    assert res.json()["type"] == haiku_type


def test_precheck_rejects_short_image(client) -> None:
    """Pydantic min_length=100 rechaza payloads vacíos."""
    res = client.post(
        "/api/scan/precheck",
        json={"image_base64": "tiny"},
    )
    assert res.status_code == 422


def test_precheck_rejects_invalid_media_type(client) -> None:
    """Solo aceptamos jpeg/png/webp."""
    res = client.post(
        "/api/scan/precheck",
        json={"image_base64": _TINY_IMG, "media_type": "image/bmp"},
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# precheck_image (function-level)


@pytest.mark.asyncio
async def test_precheck_image_no_api_key_returns_unclear() -> None:
    """Sin ANTHROPIC_API_KEY, devolvemos unclear sin llamar al SDK."""
    fake_settings = type("S", (), {"anthropic_api_key": ""})()
    with patch(
        "app.services.smart_scanner.get_settings", return_value=fake_settings
    ):
        result = await precheck_image(_TINY_IMG)
    assert result.type == "unclear"
    assert "no-api-key" in result.raw


@pytest.mark.asyncio
async def test_precheck_image_haiku_returns_plate() -> None:
    """Haiku responde 'plate' → result.type=plate."""
    fake_settings = type("S", (), {"anthropic_api_key": "sk-test"})()
    fake_resp = _fake_anthropic_response("plate")
    fake_client = type(
        "C", (), {"messages": type(
            "M", (), {"create": AsyncMock(return_value=fake_resp)}
        )()}
    )()

    with patch(
        "app.services.smart_scanner.get_settings", return_value=fake_settings
    ), patch("anthropic.AsyncAnthropic", return_value=fake_client):
        result = await precheck_image(_TINY_IMG)
    assert result.type == "plate"


@pytest.mark.asyncio
async def test_precheck_image_extracts_first_word_when_haiku_adds_explanation() -> None:
    """Haiku a veces ignora el prompt y agrega explicación. Tomamos
    solo la primera palabra alfanumérica."""
    fake_settings = type("S", (), {"anthropic_api_key": "sk-test"})()
    fake_resp = _fake_anthropic_response("invoice (es una factura SAT)")
    fake_client = type(
        "C", (), {"messages": type(
            "M", (), {"create": AsyncMock(return_value=fake_resp)}
        )()}
    )()

    with patch(
        "app.services.smart_scanner.get_settings", return_value=fake_settings
    ), patch("anthropic.AsyncAnthropic", return_value=fake_client):
        result = await precheck_image(_TINY_IMG)
    assert result.type == "invoice"


@pytest.mark.asyncio
async def test_precheck_image_unknown_word_falls_back_to_unclear() -> None:
    """Si Haiku devuelve algo no esperado, defaulteamos a unclear."""
    fake_settings = type("S", (), {"anthropic_api_key": "sk-test"})()
    fake_resp = _fake_anthropic_response("dunno what this is")
    fake_client = type(
        "C", (), {"messages": type(
            "M", (), {"create": AsyncMock(return_value=fake_resp)}
        )()}
    )()

    with patch(
        "app.services.smart_scanner.get_settings", return_value=fake_settings
    ), patch("anthropic.AsyncAnthropic", return_value=fake_client):
        result = await precheck_image(_TINY_IMG)
    assert result.type == "unclear"


@pytest.mark.asyncio
async def test_precheck_image_swallows_anthropic_errors() -> None:
    """Si el SDK throws (red, quota, 5xx) → unclear, no se propaga.
    El frontend tiene fallback al smart_scan completo de todas formas."""
    fake_settings = type("S", (), {"anthropic_api_key": "sk-test"})()
    fake_client = type(
        "C", (), {"messages": type(
            "M", (), {
                "create": AsyncMock(side_effect=RuntimeError("network down"))
            }
        )()}
    )()

    with patch(
        "app.services.smart_scanner.get_settings", return_value=fake_settings
    ), patch("anthropic.AsyncAnthropic", return_value=fake_client):
        result = await precheck_image(_TINY_IMG)
    assert result.type == "unclear"
    assert "error" in result.raw
