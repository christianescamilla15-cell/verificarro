"""Tests del init de Sentry SDK (MOD-010).

`_init_sentry()` debe:
- No fallar si DSN está vacío (modo dev)
- Inicializar el SDK si DSN está set
- Filtrar HTTPException 4xx + RateLimitExceeded en before_send (no
  llenan cuota de Sentry)
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

from fastapi import HTTPException
from slowapi.errors import RateLimitExceeded


def test_init_sentry_no_op_when_dsn_empty() -> None:
    """Sin SENTRY_DSN configurado, _init_sentry retorna sin llamar al SDK."""
    from app import main
    fake_settings = MagicMock()
    fake_settings.sentry_dsn = ""
    fake_settings.env = "test"
    fake_settings.sentry_traces_sample_rate = 0.1

    with patch("app.main.get_settings", return_value=fake_settings), \
         patch("sentry_sdk.init") as mock_init:
        main._init_sentry()
        assert not mock_init.called


def test_init_sentry_calls_sdk_when_dsn_set() -> None:
    """Con DSN set, sentry_sdk.init se llama con los kwargs correctos."""
    from app import main
    fake_settings = MagicMock()
    fake_settings.sentry_dsn = "https://abc@o123.sentry.io/456"
    fake_settings.env = "production"
    fake_settings.sentry_traces_sample_rate = 0.1

    with patch("app.main.get_settings", return_value=fake_settings), \
         patch("sentry_sdk.init") as mock_init:
        main._init_sentry()
        assert mock_init.called
        kwargs = mock_init.call_args.kwargs
        assert kwargs["dsn"] == "https://abc@o123.sentry.io/456"
        assert kwargs["traces_sample_rate"] == 0.1
        assert kwargs["send_default_pii"] is False  # privacy LFPDPPP
        assert kwargs["environment"] == "production"
        assert "verificarro@" in kwargs["release"]
        assert callable(kwargs["before_send"])


def test_before_send_drops_http_4xx() -> None:
    """HTTPException con status <500 NO debe ir a Sentry (errores de cliente)."""
    from app.main import _sentry_before_send

    exc = HTTPException(status_code=404, detail="Not Found")
    event = {"some": "data"}
    hint = {"exc_info": (HTTPException, exc, None)}

    result = _sentry_before_send(event, hint)
    assert result is None  # filtrado


def test_before_send_drops_rate_limit_exceptions() -> None:
    """RateLimitExceeded NO debe ir a Sentry (esperado, no es bug)."""
    from app.main import _sentry_before_send

    exc = RateLimitExceeded(limit=MagicMock(error_message="5 per 1 minute"))
    event = {"some": "data"}
    hint = {"exc_info": (RateLimitExceeded, exc, None)}

    result = _sentry_before_send(event, hint)
    assert result is None


def test_before_send_keeps_500_errors() -> None:
    """Errores reales 500+ SÍ van a Sentry — eso queremos saber."""
    from app.main import _sentry_before_send

    exc = HTTPException(status_code=500, detail="Internal Server Error")
    event = {"original": "event"}
    hint = {"exc_info": (HTTPException, exc, None)}

    result = _sentry_before_send(event, hint)
    assert result == event


def test_before_send_keeps_unhandled_exceptions() -> None:
    """Excepciones no-HTTP (e.g. ValueError, ZeroDivisionError) van a Sentry."""
    from app.main import _sentry_before_send

    exc = ValueError("inesperado")
    event = {"original": "event"}
    hint = {"exc_info": (ValueError, exc, None)}

    result = _sentry_before_send(event, hint)
    assert result == event


def test_before_send_handles_no_exc_info() -> None:
    """Si el hint no trae exc_info (e.g. mensaje de log), devuelve event."""
    from app.main import _sentry_before_send

    event = {"message": "log entry"}
    hint = {}

    result = _sentry_before_send(event, hint)
    assert result == event
