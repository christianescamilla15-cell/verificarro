"""Tests del cliente 2Captcha. Mockea httpx — no hace red real."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.services import captcha_solver
from app.services.captcha_solver import solve_recaptcha_v2


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch):
    """Reduce el polling interval para que los tests no tarden 5s+ por iteración."""
    monkeypatch.setattr(captcha_solver, "_POLL_INTERVAL_SEC", 0.01)
    monkeypatch.setattr(captcha_solver, "_POLL_MAX_SECONDS", 1)


def _ok_response(text: str) -> httpx.Response:
    return httpx.Response(
        200, text=text, request=httpx.Request("POST", "https://2captcha.com/in.php")
    )


@pytest.mark.asyncio
async def test_no_api_key_returns_none(monkeypatch) -> None:
    """Sin API key, no llamamos a 2Captcha y devolvemos None inmediato."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("CAPTCHA_SOLVER_API_KEY", "")

    out = await solve_recaptcha_v2(
        sitekey="6LcSITEKEY", page_url="https://example.com"
    )
    assert out is None
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_submit_rejected_returns_none(monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("CAPTCHA_SOLVER_API_KEY", "test-key-123")

    async def _post(self, url, **kwargs):  # noqa: ARG001
        return _ok_response("ERROR_WRONG_USER_KEY")

    with patch.object(httpx.AsyncClient, "post", _post):
        out = await solve_recaptcha_v2("KEY", "https://example.com")

    assert out is None
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_full_flow_success(monkeypatch) -> None:
    """submit OK → polling devuelve token al 2do intento."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("CAPTCHA_SOLVER_API_KEY", "test-key-123")
    monkeypatch.setattr(captcha_solver, "_POLL_MAX_SECONDS", 5)
    monkeypatch.setattr(captcha_solver, "_POLL_INTERVAL_SEC", 0.05)

    poll_call = {"n": 0}

    async def _post(self, url, **kwargs):  # noqa: ARG001
        return _ok_response("OK|task-12345")

    async def _get(self, url, **kwargs):  # noqa: ARG001
        poll_call["n"] += 1
        if poll_call["n"] < 2:
            return _ok_response("CAPCHA_NOT_READY")
        return _ok_response("OK|03AGdBq25token-resuelto-por-humano")

    with patch.object(httpx.AsyncClient, "post", _post), \
         patch.object(httpx.AsyncClient, "get", _get):
        out = await solve_recaptcha_v2("KEY", "https://example.com")

    assert out == "03AGdBq25token-resuelto-por-humano"
    assert poll_call["n"] == 2
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_polling_timeout_returns_none(monkeypatch) -> None:
    """Si 2Captcha tarda más de _POLL_MAX_SECONDS, devolvemos None."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("CAPTCHA_SOLVER_API_KEY", "test-key-123")

    async def _post(self, url, **kwargs):  # noqa: ARG001
        return _ok_response("OK|task-stuck")

    async def _get(self, url, **kwargs):  # noqa: ARG001
        return _ok_response("CAPCHA_NOT_READY")

    with patch.object(httpx.AsyncClient, "post", _post), \
         patch.object(httpx.AsyncClient, "get", _get):
        out = await solve_recaptcha_v2("KEY", "https://example.com")

    assert out is None
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_polling_error_returns_none(monkeypatch) -> None:
    """Si 2Captcha responde ERROR_CAPTCHA_UNSOLVABLE durante polling, abort."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("CAPTCHA_SOLVER_API_KEY", "test-key-123")
    monkeypatch.setattr(captcha_solver, "_POLL_MAX_SECONDS", 5)
    monkeypatch.setattr(captcha_solver, "_POLL_INTERVAL_SEC", 0.05)

    async def _post(self, url, **kwargs):  # noqa: ARG001
        return _ok_response("OK|task-fail")

    async def _get(self, url, **kwargs):  # noqa: ARG001
        return _ok_response("ERROR_CAPTCHA_UNSOLVABLE")

    with patch.object(httpx.AsyncClient, "post", _post), \
         patch.object(httpx.AsyncClient, "get", _get):
        out = await solve_recaptcha_v2("KEY", "https://example.com")

    assert out is None
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_network_error_returns_none(monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("CAPTCHA_SOLVER_API_KEY", "test-key-123")

    async def _raise(self, url, **kwargs):  # noqa: ARG001
        raise httpx.TimeoutException("simulated")

    with patch.object(httpx.AsyncClient, "post", _raise):
        out = await solve_recaptcha_v2("KEY", "https://example.com")

    assert out is None
    get_settings.cache_clear()
