"""Tests del endpoint público /api/config — para WhatsApp toggle + pricing."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_public_config_returns_pricing() -> None:
    with TestClient(app) as client:
        res = client.get("/api/config")
    assert res.status_code == 200
    body = res.json()
    assert "pricing" in body
    assert body["pricing"]["basic_mxn"] == 49.0
    assert body["pricing"]["premium_mxn"] == 99.0
    assert body["pricing"]["search_mxn"] == 199.0
    assert body["pricing"]["dealer_mxn"] == 1499.0


def test_public_config_whatsapp_disabled_when_empty(monkeypatch) -> None:
    """Si WHATSAPP_SUPPORT_NUMBER está vacío, whatsapp_enabled=False."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("WHATSAPP_SUPPORT_NUMBER", "")
    with TestClient(app) as client:
        res = client.get("/api/config")
    body = res.json()
    assert body["whatsapp_enabled"] is False
    assert body["whatsapp_number"] is None
    get_settings.cache_clear()


def test_public_config_whatsapp_enabled_when_set(monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("WHATSAPP_SUPPORT_NUMBER", "5215512345678")
    with TestClient(app) as client:
        res = client.get("/api/config")
    body = res.json()
    assert body["whatsapp_enabled"] is True
    assert body["whatsapp_number"] == "5215512345678"
    get_settings.cache_clear()
