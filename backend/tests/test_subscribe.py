"""Tests del endpoint /api/payments/subscribe (MP preapproval real).

MOD-013 agregó:
- Persistencia: subscribe inserta Payment row con tier=search/dealer
- Webhook handler para topic=preapproval que actualiza el Payment según
  el status del preapproval (authorized → PAID, cancelled → FAILED)
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Payment, PaymentStatus
from app.db.session import get_async_session
from app.main import app
from app.services.mercadopago import MpPreapprovalInfo, PreapprovalResult


@pytest_asyncio.fixture
async def db_factory():
    """Engine in-memory aislado por test."""
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


def _fake_preapproval(suffix: str = "x") -> PreapprovalResult:
    """Cada test debe pasar un suffix único para evitar UNIQUE collision
    en `mp_external_reference`."""
    return PreapprovalResult(
        preapproval_id=f"preapp-test-{suffix}",
        init_point=f"https://www.mercadopago.com.mx/preapproval/{suffix}",
        external_reference=f"ext-ref-sub-{suffix}",
        status="pending",
    )


# ---------------------------------------------------------------------------
# /api/payments/subscribe


def test_subscribe_search_tier_creates_preapproval(client) -> None:
    with patch(
        "app.api.payments.create_preapproval",
        return_value=_fake_preapproval("search"),
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
    assert "mercadopago" in body["init_point"]
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


def test_subscribe_dealer_tier_charges_1499(client) -> None:
    with patch(
        "app.api.payments.create_preapproval",
        return_value=_fake_preapproval("dealer"),
    ) as mock:
        res = client.post(
            "/api/payments/subscribe",
            json={"tier": "dealer", "payer_email": "dealer@auto.mx"},
        )
    assert res.status_code == 200
    assert res.json()["amount_mxn"] == 1499.0
    assert "Dealer" in mock.call_args.kwargs["reason"]


def test_subscribe_persists_payment_row(client, db_factory) -> None:
    """MOD-013: subscribe inserta Payment row PENDING en DB para que el
    webhook preapproval pueda encontrarlo."""
    with patch(
        "app.api.payments.create_preapproval",
        return_value=_fake_preapproval("persist"),
    ):
        client.post(
            "/api/payments/subscribe",
            json={"tier": "search", "payer_email": "persist@example.com"},
        )

    import asyncio

    async def _check():
        async with db_factory() as s:
            r = await s.execute(
                select(Payment).where(
                    Payment.mp_external_reference == "ext-ref-sub-persist"
                )
            )
            return r.scalar_one()

    p = asyncio.get_event_loop().run_until_complete(_check())
    assert p.tier == "search"
    assert p.status == PaymentStatus.PENDING
    assert p.amount_mxn == 199.0
    assert p.payer_email == "persist@example.com"
    assert p.mp_preference_id == "preapp-test-persist"  # almacena preapproval_id


def test_subscribe_basic_tier_rejected(client) -> None:
    """Solo search/dealer son válidos en /subscribe; basic/premium usan
    /checkout (one-time)."""
    res = client.post(
        "/api/payments/subscribe",
        json={"tier": "basic", "payer_email": "x@y.com"},
    )
    assert res.status_code == 422


def test_subscribe_invalid_email_rejected(client) -> None:
    res = client.post(
        "/api/payments/subscribe",
        json={"tier": "search", "payer_email": "x"},
    )
    assert res.status_code == 422


def test_subscribe_mp_failure_returns_503(client) -> None:
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


# ---------------------------------------------------------------------------
# Webhook topic=preapproval (MOD-013)


def _seed_preapproval_payment(db_factory, ext_ref: str, tier: str = "search") -> str:
    """Helper: crea un Payment PENDING simulando que pasó por subscribe."""
    import asyncio

    async def _seed() -> str:
        async with db_factory() as s:
            p = Payment(
                amount_mxn=199.0 if tier == "search" else 1499.0,
                tier=tier,
                status=PaymentStatus.PENDING,
                mp_external_reference=ext_ref,
                mp_preference_id=f"preapp-{ext_ref}",
                payer_email="sub@example.com",
            )
            s.add(p)
            await s.commit()
            return p.id

    return asyncio.get_event_loop().run_until_complete(_seed())


def test_webhook_preapproval_authorized_marks_payment_paid(
    client, db_factory,
) -> None:
    ext_ref = "preapp-auth"
    payment_id = _seed_preapproval_payment(db_factory, ext_ref)

    info = MpPreapprovalInfo(
        preapproval_id=f"preapp-{ext_ref}",
        status="authorized",
        external_reference=ext_ref,
        payer_email="sub@example.com",
        transaction_amount=199.0,
        next_payment_date="2026-06-01",
    )
    with patch(
        "app.api.payments.get_preapproval_info", return_value=info,
    ):
        res = client.post(
            "/api/payments/webhook",
            json={"type": "preapproval", "data": {"id": f"preapp-{ext_ref}"}},
        )
    assert res.status_code == 200
    body = res.json()
    assert body.get("payment_status") == "paid"

    import asyncio

    async def _check():
        async with db_factory() as s:
            r = await s.execute(
                select(Payment).where(Payment.id == payment_id)
            )
            return r.scalar_one()

    p = asyncio.get_event_loop().run_until_complete(_check())
    assert p.status == PaymentStatus.PAID
    assert p.paid_at is not None


def test_webhook_preapproval_cancelled_marks_payment_failed(
    client, db_factory,
) -> None:
    ext_ref = "preapp-cancel"
    _seed_preapproval_payment(db_factory, ext_ref)

    info = MpPreapprovalInfo(
        preapproval_id=f"preapp-{ext_ref}",
        status="cancelled",
        external_reference=ext_ref,
        payer_email="sub@example.com",
        transaction_amount=199.0,
        next_payment_date=None,
    )
    with patch(
        "app.api.payments.get_preapproval_info", return_value=info,
    ):
        res = client.post(
            "/api/payments/webhook",
            json={"type": "preapproval", "data": {"id": f"preapp-{ext_ref}"}},
        )
    assert res.status_code == 200
    assert res.json().get("payment_status") == "failed"


def test_webhook_preapproval_idempotent_duplicate(client, db_factory) -> None:
    """Dos webhooks consecutivos con mismo status → segundo no-op."""
    ext_ref = "preapp-dup"
    _seed_preapproval_payment(db_factory, ext_ref)

    info = MpPreapprovalInfo(
        preapproval_id=f"preapp-{ext_ref}",
        status="authorized",
        external_reference=ext_ref,
        payer_email="sub@example.com",
        transaction_amount=199.0,
        next_payment_date="2026-06-01",
    )
    with patch("app.api.payments.get_preapproval_info", return_value=info):
        client.post(
            "/api/payments/webhook",
            json={"type": "preapproval", "data": {"id": f"preapp-{ext_ref}"}},
        )
        # Segundo webhook idéntico
        res = client.post(
            "/api/payments/webhook",
            json={"type": "preapproval", "data": {"id": f"preapp-{ext_ref}"}},
        )
    assert res.status_code == 200
    assert res.json().get("ignored") == "idempotent-duplicate"


def test_webhook_preapproval_unknown_external_reference_acked(client) -> None:
    """external_reference que no existe en DB → ack 200 sin crear."""
    info = MpPreapprovalInfo(
        preapproval_id="preapp-orphan",
        status="authorized",
        external_reference="ref-orphan-no-existe",
        payer_email="x@x.com",
        transaction_amount=199.0,
        next_payment_date=None,
    )
    with patch("app.api.payments.get_preapproval_info", return_value=info):
        res = client.post(
            "/api/payments/webhook",
            json={"type": "preapproval", "data": {"id": "preapp-orphan"}},
        )
    assert res.status_code == 200
    assert res.json().get("ignored") == "unknown-external-reference"


def test_webhook_preapproval_pending_no_op(client, db_factory) -> None:
    """status=pending (default post-create) → Payment se mantiene PENDING."""
    ext_ref = "preapp-pending"
    _seed_preapproval_payment(db_factory, ext_ref)

    info = MpPreapprovalInfo(
        preapproval_id=f"preapp-{ext_ref}",
        status="pending",
        external_reference=ext_ref,
        payer_email="sub@example.com",
        transaction_amount=199.0,
        next_payment_date=None,
    )
    with patch("app.api.payments.get_preapproval_info", return_value=info):
        res = client.post(
            "/api/payments/webhook",
            json={"type": "preapproval", "data": {"id": f"preapp-{ext_ref}"}},
        )
    # status sigue PENDING → no cambio → idempotent
    assert res.status_code == 200
    assert res.json().get("ignored") == "idempotent-duplicate"
