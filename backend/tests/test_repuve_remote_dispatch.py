"""Tests del dispatch del backend al sidecar REPUVE-MX (MOD-040).

Cubre:
- query() dispatcha a _query_remote cuando REPUVE_SCRAPER_URL está set
- _query_remote serializa correctamente success de 200
- _query_remote degrada a queried=False en HTTP 4xx/5xx
- _query_remote degrada en timeout de red
- _query_remote envía Bearer token cuando está configurado
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.models.report import RepuveResult
from app.scrapers.repuve import _query_remote, query


def _fake_settings(scraper_url: str = "", scraper_token: str = ""):
    """Settings mock con los campos mínimos que usa repuve.query()."""
    return type("S", (), {
        "repuve_scraper_url": scraper_url,
        "repuve_scraper_token": scraper_token,
        "repuve_scraper_timeout_sec": 10.0,
        "repuve_retry_attempts": 1,
        "repuve_rate_limit_per_sec": 0,  # disable throttle en tests
    })()


def _fake_http_response(status_code: int, body: dict | str):
    """Construye un httpx.Response sintético sin abrir conexión real."""
    if isinstance(body, dict):
        content = json.dumps(body).encode()
        headers = {"content-type": "application/json"}
    else:
        content = body.encode() if isinstance(body, str) else body
        headers = {"content-type": "text/plain"}
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers=headers,
    )


# ---------------------------------------------------------------------------
# query() dispatch logic


@pytest.mark.asyncio
async def test_query_uses_local_when_scraper_url_empty() -> None:
    """Sin REPUVE_SCRAPER_URL, el dispatch va al path local (_run_query)."""
    settings = _fake_settings(scraper_url="")
    with patch(
        "app.scrapers.repuve.get_settings", return_value=settings,
    ), patch(
        "app.scrapers.repuve._query_remote",
    ) as mock_remote, patch(
        "app.scrapers.repuve._run_query",
        new=AsyncMock(return_value=RepuveResult(queried=True, plate="ABC123")),
    ) as mock_local:
        await query(plate="ABC123")
    mock_remote.assert_not_called()
    mock_local.assert_called_once()


@pytest.mark.asyncio
async def test_query_dispatches_to_remote_when_scraper_url_set() -> None:
    """Con REPUVE_SCRAPER_URL set, dispatch va al sidecar."""
    settings = _fake_settings(
        scraper_url="https://scraper-mx.example.com",
        scraper_token="secret123",
    )
    with patch(
        "app.scrapers.repuve.get_settings", return_value=settings,
    ), patch(
        "app.scrapers.repuve._query_remote",
        new=AsyncMock(return_value=RepuveResult(queried=True, plate="ABC123")),
    ) as mock_remote, patch(
        "app.scrapers.repuve._run_query",
    ) as mock_local:
        result = await query(plate="ABC123")
    mock_remote.assert_called_once()
    mock_local.assert_not_called()
    assert result.queried is True


@pytest.mark.asyncio
async def test_query_invalid_input_short_circuits_before_dispatch() -> None:
    """Validación local (placa con 4 chars) no llega al sidecar."""
    settings = _fake_settings(scraper_url="https://scraper-mx.example.com")
    with patch(
        "app.scrapers.repuve.get_settings", return_value=settings,
    ), patch(
        "app.scrapers.repuve._query_remote",
    ) as mock_remote:
        # 4 chars sobrevive normalize pero falla _is_valid_plate (5-7).
        result = await query(plate="ABCD")
    mock_remote.assert_not_called()
    assert result.queried is False
    assert "inválida" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# _query_remote — HTTP layer


@pytest.mark.asyncio
async def test_query_remote_success_returns_serialized_result() -> None:
    """Sidecar responde 200 con JSON → deserializa a RepuveResult."""
    body = {
        "queried": True,
        "plate": "ABC123",
        "vin": None,
        "is_stolen": False,
        "has_legal_status": True,
        "raw_status": "sin_reportes",
        "error": None,
    }
    fake_resp = _fake_http_response(200, body)

    async def _fake_post(*a, **kw):
        return fake_resp

    with patch.object(httpx.AsyncClient, "post", new=_fake_post):
        result = await _query_remote(
            "ABC123", None,
            url="https://scraper-mx.example.com",
            token="secret",
            timeout=5.0,
        )
    assert result.queried is True
    assert result.plate == "ABC123"
    assert result.is_stolen is False
    assert result.raw_status == "sin_reportes"


@pytest.mark.asyncio
async def test_query_remote_includes_bearer_when_token_set() -> None:
    """Cuando token está set, el header Authorization debe estar presente."""
    captured: dict = {}

    async def _fake_post(self, url, json=None, headers=None):  # noqa: ARG001
        captured["headers"] = headers
        return _fake_http_response(200, {"queried": True})

    with patch.object(httpx.AsyncClient, "post", new=_fake_post):
        await _query_remote(
            "ABC123", None,
            url="https://scraper-mx.example.com",
            token="my-secret-token",
            timeout=5.0,
        )
    assert captured["headers"]["Authorization"] == "Bearer my-secret-token"


@pytest.mark.asyncio
async def test_query_remote_omits_bearer_when_token_empty() -> None:
    """Token vacío → no Authorization header (sidecar rechazará con 401)."""
    captured: dict = {}

    async def _fake_post(self, url, json=None, headers=None):  # noqa: ARG001
        captured["headers"] = headers
        return _fake_http_response(401, {"detail": "no token"})

    with patch.object(httpx.AsyncClient, "post", new=_fake_post):
        result = await _query_remote(
            "ABC123", None,
            url="https://scraper-mx.example.com",
            token="",
            timeout=5.0,
        )
    assert "Authorization" not in captured["headers"]
    assert result.queried is False
    assert "401" in (result.error or "")


@pytest.mark.asyncio
async def test_query_remote_handles_500_gracefully() -> None:
    """Sidecar 5xx → degradación limpia con error claro, NO raise."""
    fake_resp = _fake_http_response(500, "Internal error")

    async def _fake_post(*a, **kw):
        return fake_resp

    with patch.object(httpx.AsyncClient, "post", new=_fake_post):
        result = await _query_remote(
            "ABC123", None,
            url="https://scraper-mx.example.com",
            token="secret",
            timeout=5.0,
        )
    assert result.queried is False
    assert "500" in (result.error or "")


@pytest.mark.asyncio
async def test_query_remote_handles_timeout_gracefully() -> None:
    """Sidecar no responde a tiempo → queried=False con mensaje claro."""

    async def _fake_post(*a, **kw):
        raise httpx.TimeoutException("read timeout")

    with patch.object(httpx.AsyncClient, "post", new=_fake_post):
        result = await _query_remote(
            "ABC123", None,
            url="https://scraper-mx.example.com",
            token="secret",
            timeout=1.0,
        )
    assert result.queried is False
    assert "timeout" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_query_remote_handles_network_error_gracefully() -> None:
    """DNS / unreachable → degradación, no raise."""

    async def _fake_post(*a, **kw):
        raise httpx.ConnectError("connection refused")

    with patch.object(httpx.AsyncClient, "post", new=_fake_post):
        result = await _query_remote(
            "ABC123", None,
            url="https://scraper-mx.example.com",
            token="secret",
            timeout=5.0,
        )
    assert result.queried is False
    assert "network" in (result.error or "").lower() or "connect" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_query_remote_handles_non_json_response() -> None:
    """Sidecar 200 pero body no-JSON (e.g. HTML error page) → degradación."""
    fake_resp = _fake_http_response(200, "<html>oops</html>")

    async def _fake_post(*a, **kw):
        return fake_resp

    with patch.object(httpx.AsyncClient, "post", new=_fake_post):
        result = await _query_remote(
            "ABC123", None,
            url="https://scraper-mx.example.com",
            token="secret",
            timeout=5.0,
        )
    assert result.queried is False
    assert "no-JSON" in (result.error or "") or "json" in (result.error or "").lower()
