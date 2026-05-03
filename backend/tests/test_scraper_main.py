"""Tests del sidecar `verificarro-scraper-mx` (app/scraper_main.py).

Cubre el endpoint POST /scrape/repuve + la lógica de auth con
REPUVE_SCRAPER_TOKEN.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.report import RepuveResult
from app.scraper_main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# /health (sin auth)


def test_health_returns_ok_without_auth(client) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["service"] == "verificarro-scraper-mx"


# ---------------------------------------------------------------------------
# Auth gating


def test_scrape_without_token_env_returns_503(client, monkeypatch) -> None:
    """Sidecar sin REPUVE_SCRAPER_TOKEN configurado → fail-closed (503)."""
    monkeypatch.delenv("REPUVE_SCRAPER_TOKEN", raising=False)
    res = client.post(
        "/scrape/repuve",
        json={"plate": "ABC123"},
        headers={"Authorization": "Bearer anything"},
    )
    assert res.status_code == 503
    assert "no configurado" in res.json()["detail"].lower()


def test_scrape_without_authorization_header_returns_401(client, monkeypatch) -> None:
    monkeypatch.setenv("REPUVE_SCRAPER_TOKEN", "secret-test")
    res = client.post("/scrape/repuve", json={"plate": "ABC123"})
    assert res.status_code == 401


def test_scrape_with_wrong_token_returns_401(client, monkeypatch) -> None:
    monkeypatch.setenv("REPUVE_SCRAPER_TOKEN", "secret-test")
    res = client.post(
        "/scrape/repuve",
        json={"plate": "ABC123"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert res.status_code == 401


def test_scrape_with_non_bearer_format_returns_401(client, monkeypatch) -> None:
    monkeypatch.setenv("REPUVE_SCRAPER_TOKEN", "secret-test")
    res = client.post(
        "/scrape/repuve",
        json={"plate": "ABC123"},
        headers={"Authorization": "Basic c2VjcmV0LXRlc3Q="},
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Body validation


def test_scrape_without_plate_or_vin_returns_400(client, monkeypatch) -> None:
    monkeypatch.setenv("REPUVE_SCRAPER_TOKEN", "secret-test")
    res = client.post(
        "/scrape/repuve",
        json={},  # ni plate ni vin
        headers={"Authorization": "Bearer secret-test"},
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Happy path — delega a repuve.query()


def test_scrape_dispatches_to_repuve_query_with_plate(client, monkeypatch) -> None:
    """Auth + body OK → llama a app.scrapers.repuve.query y serializa."""
    monkeypatch.setenv("REPUVE_SCRAPER_TOKEN", "secret-test")
    fake_result = RepuveResult(
        queried=True, plate="ABC123", is_stolen=False, raw_status="sin_reportes",
    )
    with patch(
        "app.scraper_main.repuve_query",
        new=AsyncMock(return_value=fake_result),
    ) as mock_q:
        res = client.post(
            "/scrape/repuve",
            json={"plate": "ABC123"},
            headers={"Authorization": "Bearer secret-test"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["queried"] is True
    assert body["plate"] == "ABC123"
    assert body["is_stolen"] is False
    assert body["raw_status"] == "sin_reportes"
    mock_q.assert_called_once_with(plate="ABC123", vin=None)


def test_scrape_serializes_failed_query_correctly(client, monkeypatch) -> None:
    """Cuando repuve.query devuelve queried=False, sidecar pasa el error."""
    monkeypatch.setenv("REPUVE_SCRAPER_TOKEN", "secret-test")
    fake_result = RepuveResult(
        queried=False, plate="XYZ999", error="captcha_required",
    )
    with patch(
        "app.scraper_main.repuve_query",
        new=AsyncMock(return_value=fake_result),
    ):
        res = client.post(
            "/scrape/repuve",
            json={"plate": "XYZ999"},
            headers={"Authorization": "Bearer secret-test"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["queried"] is False
    assert body["error"] == "captcha_required"
