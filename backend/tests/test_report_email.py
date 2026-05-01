"""Tests del send_report_email en modo dev (sin SMTP) y prod (mocked)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.email import send_report_email


@pytest.mark.asyncio
async def test_dev_mode_stub_no_smtp(monkeypatch, capsys) -> None:
    """Sin SMTP_HOST, manda al stdout en lugar de SMTP real."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SMTP_HOST", "")

    await send_report_email(
        "user@example.com",
        b"fake pdf bytes" * 100,
        title_hint="Honda Civic 2018",
        score=85, risk_level="green", report_id="abcd1234-test",
        report_url="https://verificarro.mx/checkout/success?...",
    )

    captured = capsys.readouterr()
    assert "user@example.com" in captured.out
    assert "Honda Civic 2018" in captured.out
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_prod_mode_calls_smtp(monkeypatch) -> None:
    """Con SMTP_HOST set, usa smtplib.SMTP."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SMTP_HOST", "smtp.resend.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "resend")
    monkeypatch.setenv("SMTP_PASSWORD", "re_test_key")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "hola@verificarro.mx")
    monkeypatch.setenv("SMTP_FROM_NAME", "Verificarro")

    captured = {"called": False, "msg": None}

    class _MockSMTP:
        def __init__(self, host, port):
            captured["host"] = host
            captured["port"] = port
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def starttls(self):
            captured["tls"] = True
        def login(self, user, password):
            captured["user"] = user
        def send_message(self, msg):
            captured["called"] = True
            captured["msg"] = msg

    with patch("app.services.email.smtplib.SMTP", _MockSMTP):
        await send_report_email(
            "user@example.com",
            b"fake pdf bytes",
            title_hint="Test", score=70, risk_level="yellow",
            report_id="report-x",
        )

    assert captured["called"] is True
    assert captured["host"] == "smtp.resend.com"
    assert captured["msg"]["To"] == "user@example.com"
    assert "70/100" in captured["msg"]["Subject"]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_smtp_failure_does_not_raise(monkeypatch) -> None:
    """Si SMTP falla, NO levantamos excepción (bloquearía el unlock)."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SMTP_HOST", "smtp.resend.com")

    class _BrokenSMTP:
        def __init__(self, *args):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def starttls(self):
            raise OSError("network down")

    with patch("app.services.email.smtplib.SMTP", _BrokenSMTP):
        # No exception expected
        await send_report_email(
            "user@example.com", b"pdf", title_hint="Test",
        )
    get_settings.cache_clear()
