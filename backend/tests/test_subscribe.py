"""Tests del endpoint /api/payments/subscribe (MP preapproval real)."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.mercadopago import PreapprovalResult


def _fake_preapproval() -> PreapprovalResult:
    return PreapprovalResult(
        preapproval_id="preapp-test-123",
        init_point="https://www.mercadopago.com.mx/preapproval/...",
        external_reference="ext-ref-sub-test",
        status="pending",
    )


def test_subscribe_search_tier_creates_preapproval() -> None:
    with TestClient(app) as client:
        with patch(
            "app.api.payments.create_preapproval",
            return_value=_fake_preapproval(),
        ) as mock:
            res = client.post(
                "/api/payments/subscribe",
                json={
                    "tier": "search",
                    "payer_email": "user@example.com",
                    "name": "Christian H",
                    "phone": "5512345678",
                },
            )
    assert res.status_code == 200
    body = res.json()
    assert body["amount_mxn"] == 199.0
    assert body["tier"] == "search"
    assert "preapproval/" in body["init_point"] or "mercadopago" in body["init_point"]
    assert mock.called
    call_kwargs = mock.call_args.kwargs
    assert call_kwargs["amount_mxn"] == 199.0
    assert "Búsqueda activa" in call_kwargs["reason"]
    # MOD-005: polling_token presente
    assert body["polling_token"]
    assert len(body["polling_token"]) == 32
    # MOD-007: activation_note comunicado al usuario
    assert "Mercado Pago" in body["activation_note"]
    assert "1 hora" in body["activation_note"]


def test_subscribe_dealer_tier_charges_1499() -> None:
    with TestClient(app) as client:
        with patch(
            "app.api.payments.create_preapproval",
            return_value=_fake_preapproval(),
        ) as mock:
            res = client.post(
                "/api/payments/subscribe",
                json={"tier": "dealer", "payer_email": "dealer@auto.mx"},
            )
    assert res.status_code == 200
    assert res.json()["amount_mxn"] == 1499.0
    assert "Dealer" in mock.call_args.kwargs["reason"]


def test_subscribe_basic_tier_rejected() -> None:
    """Solo search/dealer son válidos en /subscribe; basic/premium usan
    /checkout (one-time)."""
    with TestClient(app) as client:
        res = client.post(
            "/api/payments/subscribe",
            json={"tier": "basic", "payer_email": "x@y.com"},
        )
    assert res.status_code == 422


def test_subscribe_invalid_email_rejected() -> None:
    with TestClient(app) as client:
        res = client.post(
            "/api/payments/subscribe",
            json={"tier": "search", "payer_email": "x"},  # too short
        )
    assert res.status_code == 422


def test_subscribe_mp_failure_returns_503() -> None:
    with TestClient(app) as client:
        with patch(
            "app.api.payments.create_preapproval",
            side_effect=RuntimeError("MP timeout"),
        ):
            res = client.post(
                "/api/payments/subscribe",
                json={"tier": "search", "payer_email": "u@example.com"},
            )
    assert res.status_code == 503
    assert "MP" in res.json()["detail"] or "suscripción" in res.json()["detail"].lower()
