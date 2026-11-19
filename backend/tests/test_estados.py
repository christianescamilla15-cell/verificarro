"""Máquinas de estado del dominio: pago, suscripción y reporte.

Reglas (docs/reglas.md, sección «Estados»):

- Pago único (webhook topic=payment):
  pending → paid | failed | refunded · failed → pending | paid (reintento)
  · paid → refunded · refunded es terminal. Un pago acreditado NO regresa
  a pending ni a failed por un webhook atrasado de otro intento.
- Suscripción (topic=preapproval): pending → paid | failed · paid → pending
  (pausa) | failed (cancelación) · failed (cancelada) es terminal.
- Reporte: preview → unlocked sólo con el pago en paid; unlocked no
  vuelve a correr el pipeline.

Las transiciones inválidas se prueban a nivel función y a nivel endpoint
(el webhook responde 200 para que MP no reintente, pero no cambia nada ni
encola el pipeline).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import session as db_session
from app.db.base import Base
from app.db.models import Payment, PaymentStatus, ReportRecord, ReportStatus
from app.db.models.payment import (
    PAYMENT_TRANSITIONS,
    SUBSCRIPTION_TRANSITIONS,
    can_transition,
)
from app.db.session import get_async_session
from app.main import app
from app.models.report import (
    ListingData,
    PriceEstimate,
    Report,
    RepuveResult,
    RiskLevel,
    Source,
)
from app.services.mercadopago import MpPaymentInfo, MpPreapprovalInfo
from app.services.report_generator import unlock_report_for_payment

P = PaymentStatus


# ---------------------------------------------------------------------------
# Tabla de transiciones (función pura)


def test_every_status_has_a_transition_row() -> None:
    """Ningún estado queda fuera de las tablas (un estado nuevo sin reglas
    haría que el webhook lanzara KeyError)."""
    assert set(PAYMENT_TRANSITIONS) == set(PaymentStatus)
    assert set(SUBSCRIPTION_TRANSITIONS) == set(PaymentStatus)


@pytest.mark.parametrize(
    ("actual", "nuevo"),
    [
        (P.PENDING, P.PAID),
        (P.PENDING, P.FAILED),
        (P.PENDING, P.REFUNDED),
        (P.FAILED, P.PENDING),   # reintento con ficha OXXO
        (P.FAILED, P.PAID),      # reintento con otra tarjeta
        (P.PAID, P.REFUNDED),
    ],
)
def test_payment_valid_transitions(actual, nuevo) -> None:
    assert can_transition(actual, nuevo) is True


@pytest.mark.parametrize(
    ("actual", "nuevo"),
    [
        (P.PAID, P.PENDING),
        (P.PAID, P.FAILED),
        (P.REFUNDED, P.PAID),
        (P.REFUNDED, P.PENDING),
        (P.REFUNDED, P.FAILED),
        (P.FAILED, P.REFUNDED),
    ],
)
def test_payment_invalid_transitions(actual, nuevo) -> None:
    assert can_transition(actual, nuevo) is False


@pytest.mark.parametrize(
    ("actual", "nuevo", "valida"),
    [
        (P.PENDING, P.PAID, True),     # authorized
        (P.PENDING, P.FAILED, True),   # cancelada antes de autorizar
        (P.PAID, P.PENDING, True),     # paused
        (P.PAID, P.FAILED, True),      # cancelled
        (P.FAILED, P.PAID, False),     # cancelada es definitiva
        (P.FAILED, P.PENDING, False),
        (P.PAID, P.REFUNDED, False),   # las suscripciones no se reembolsan por aquí
    ],
)
def test_subscription_transitions(actual, nuevo, valida) -> None:
    assert can_transition(actual, nuevo, subscription=True) is valida


@pytest.mark.parametrize("estado", list(PaymentStatus))
def test_same_status_is_not_a_transition(estado) -> None:
    """El duplicado se atiende antes como no-op idempotente."""
    assert can_transition(estado, estado) is False
    assert can_transition(estado, estado, subscription=True) is False


# ---------------------------------------------------------------------------
# Webhook: las transiciones inválidas no cambian nada ni encolan el pipeline


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


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _seed(db_factory, ref: str, status: PaymentStatus, tier: str = "basic") -> str:
    async def _go() -> str:
        async with db_factory() as s:
            p = Payment(
                amount_mxn=49.0 if tier == "basic" else 199.0,
                tier=tier,
                status=status,
                mp_external_reference=ref,
                mp_preference_id=f"pref-{ref}",
                paid_at=datetime.now(UTC) if status == P.PAID else None,
            )
            s.add(p)
            await s.commit()
            return p.id

    return _run(_go())


def _status(db_factory, payment_id: str) -> PaymentStatus:
    async def _go():
        async with db_factory() as s:
            r = await s.execute(select(Payment).where(Payment.id == payment_id))
            return r.scalar_one().status

    return _run(_go())


def _payment_webhook(client, ref: str, mp_status: str, amount: float = 49.0):
    info = MpPaymentInfo(
        payment_id=f"mp-{ref}-{mp_status}",
        status=mp_status,
        status_detail="x",
        external_reference=ref,
        transaction_amount=amount,
    )
    with patch("app.api.payments.get_payment_info", return_value=info), patch(
        "app.api.payments.generate_report_for_payment", new=AsyncMock(),
    ) as gen, patch(
        "app.api.payments.unlock_report_for_payment", new=AsyncMock(),
    ) as unlock:
        res = client.post(
            "/api/payments/webhook",
            json={"type": "payment", "data": {"id": info.payment_id}},
        )
    return res, gen, unlock


@pytest.mark.parametrize("mp_status", ["pending", "in_process", "rejected", "cancelled"])
def test_webhook_stale_attempt_cannot_unpay_a_paid_payment(client, db_factory, mp_status) -> None:
    """Pago acreditado + webhook atrasado de otro intento (ficha OXXO
    pendiente, tarjeta rechazada) → se ignora y el pago sigue en paid."""
    ref = f"paid-then-{mp_status}"
    pid = _seed(db_factory, ref, P.PAID)

    res, gen, unlock = _payment_webhook(client, ref, mp_status)

    assert res.status_code == 200
    assert res.json()["ignored"] == "invalid-transition"
    assert _status(db_factory, pid) == P.PAID
    gen.assert_not_called()
    unlock.assert_not_called()


def test_webhook_refunded_is_terminal(client, db_factory) -> None:
    """Un pago reembolsado no se vuelve a acreditar ni re-encola el reporte."""
    pid = _seed(db_factory, "refunded-ref", P.REFUNDED)

    res, gen, unlock = _payment_webhook(client, "refunded-ref", "approved")

    assert res.json()["ignored"] == "invalid-transition"
    assert _status(db_factory, pid) == P.REFUNDED
    gen.assert_not_called()
    unlock.assert_not_called()


def test_webhook_failed_then_approved_retry_is_accepted(client, db_factory) -> None:
    """Tarjeta rechazada y reintento aprobado con el mismo external_reference."""
    pid = _seed(db_factory, "retry-ref", P.FAILED)

    res, gen, _ = _payment_webhook(client, "retry-ref", "approved")

    assert res.status_code == 200
    assert res.json()["status"] == "paid"
    assert _status(db_factory, pid) == P.PAID
    gen.assert_called_once_with(pid)


def test_webhook_paid_to_refunded_is_accepted(client, db_factory) -> None:
    pid = _seed(db_factory, "refund-ref", P.PAID)

    res, gen, _ = _payment_webhook(client, "refund-ref", "refunded")

    assert res.json()["status"] == "refunded"
    assert _status(db_factory, pid) == P.REFUNDED
    gen.assert_not_called()


@pytest.mark.parametrize("monto", [1.0, 48.98, 99.0])
def test_webhook_amount_mismatch_does_not_mark_paid(client, db_factory, monto) -> None:
    """M-3: si MP reporta un monto distinto al cobrado (tolerancia 0.01), alguien
    pagó una preferencia más barata con nuestro external_reference: no se
    acredita ni se desbloquea el reporte."""
    pid = _seed(db_factory, f"monto-{monto}", P.PENDING)

    res, gen, unlock = _payment_webhook(client, f"monto-{monto}", "approved", amount=monto)

    assert res.json()["ignored"] == "amount-mismatch"
    assert _status(db_factory, pid) == P.PENDING
    gen.assert_not_called()
    unlock.assert_not_called()


def test_webhook_amount_within_tolerance_is_paid(client, db_factory) -> None:
    pid = _seed(db_factory, "monto-ok", P.PENDING)

    res, gen, _ = _payment_webhook(client, "monto-ok", "approved", amount=49.005)

    assert res.json()["status"] == "paid"
    assert _status(db_factory, pid) == P.PAID
    gen.assert_called_once_with(pid)


def _preapproval_webhook(client, ref: str, mp_status: str):
    info = MpPreapprovalInfo(
        preapproval_id=f"preapp-{ref}",
        status=mp_status,
        external_reference=ref,
        payer_email="sub@example.com",
        transaction_amount=199.0,
        next_payment_date=None,
    )
    with patch("app.api.payments.get_preapproval_info", return_value=info):
        return client.post(
            "/api/payments/webhook",
            json={"type": "preapproval", "data": {"id": info.preapproval_id}},
        )


def test_subscription_cancelled_cannot_be_reauthorized(client, db_factory) -> None:
    """La cancelación de un preapproval es definitiva en MP."""
    pid = _seed(db_factory, "sub-cancelada", P.FAILED, tier="search")

    res = _preapproval_webhook(client, "sub-cancelada", "authorized")

    assert res.json()["ignored"] == "invalid-transition"
    assert _status(db_factory, pid) == P.FAILED


def test_subscription_pause_moves_paid_to_pending(client, db_factory) -> None:
    pid = _seed(db_factory, "sub-pausada", P.PAID, tier="search")

    res = _preapproval_webhook(client, "sub-pausada", "paused")

    assert res.json()["payment_status"] == "pending"
    assert _status(db_factory, pid) == P.PENDING


# ---------------------------------------------------------------------------
# Reporte: preview → unlocked


@pytest_asyncio.fixture
async def engine_factory():
    """Factory global (report_generator usa get_session_factory())."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    db_session._engine = engine
    db_session._session_factory = factory
    yield factory
    db_session._engine = None
    db_session._session_factory = None
    await engine.dispose()


async def _seed_preview(factory, pay_status: PaymentStatus, rep_status: ReportStatus):
    async with factory() as s:
        pay = Payment(
            amount_mxn=49.0,
            status=pay_status,
            mp_external_reference=f"unlock-{pay_status.value}-{rep_status.value}",
            plate="ABC123D",
        )
        s.add(pay)
        await s.flush()
        rep = ReportRecord(
            listing_hash="h" * 64,
            score=50,
            risk_level="yellow",
            status=rep_status,
            plate="ABC123D",
            report_json={"preview": True},
            expires_at=datetime.now(UTC) + timedelta(hours=24),
            payment_id=pay.id,
        )
        s.add(rep)
        await s.commit()
        return pay.id, rep.id


async def _report(factory, report_id: str) -> ReportRecord:
    async with factory() as s:
        r = await s.execute(select(ReportRecord).where(ReportRecord.id == report_id))
        return r.scalar_one()


def _full_report() -> Report:
    return Report(
        score=82,
        risk_level=RiskLevel.GREEN,
        summary="Reporte completo de prueba",
        listing=ListingData(
            source=Source.MANUAL, title="Honda Civic 2018", price_mxn=230_000,
            year=2018, make="Honda", model="Civic", kilometers=80_000,
            location="CDMX",
        ),
        repuve=RepuveResult(queried=True, is_stolen=False, has_legal_status=True),
        price=PriceEstimate(comparables_count=0),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("pay_status", [P.PENDING, P.FAILED, P.REFUNDED])
async def test_unlock_requires_paid_payment(engine_factory, pay_status) -> None:
    """Sin pago acreditado el reporte se queda en preview y no corre el pipeline."""
    pay_id, rep_id = await _seed_preview(engine_factory, pay_status, ReportStatus.PREVIEW)
    with patch("app.services.report_generator.run_pipeline", new=AsyncMock()) as pipe:
        result = await unlock_report_for_payment(pay_id)

    assert result is None
    pipe.assert_not_called()
    assert (await _report(engine_factory, rep_id)).status == ReportStatus.PREVIEW


@pytest.mark.asyncio
async def test_unlock_preview_to_unlocked_runs_pipeline(engine_factory) -> None:
    pay_id, rep_id = await _seed_preview(engine_factory, P.PAID, ReportStatus.PREVIEW)
    with patch(
        "app.services.report_generator.run_pipeline",
        new=AsyncMock(return_value=_full_report()),
    ) as pipe, patch(
        "app.services.report_generator._apply_photo_dedup", new=AsyncMock(),
    ):
        result = await unlock_report_for_payment(pay_id)

    assert result == rep_id
    pipe.assert_awaited_once()
    rep = await _report(engine_factory, rep_id)
    assert rep.status == ReportStatus.UNLOCKED
    assert rep.score == 82
    assert rep.report_json["summary"] == "Reporte completo de prueba"


@pytest.mark.asyncio
async def test_unlock_already_unlocked_does_not_rerun_pipeline(engine_factory) -> None:
    """unlocked es el estado final del reporte: un segundo webhook no vuelve
    a gastar el análisis IA."""
    pay_id, rep_id = await _seed_preview(engine_factory, P.PAID, ReportStatus.UNLOCKED)
    with patch("app.services.report_generator.run_pipeline", new=AsyncMock()) as pipe:
        result = await unlock_report_for_payment(pay_id)

    assert result == rep_id
    pipe.assert_not_called()
    assert (await _report(engine_factory, rep_id)).status == ReportStatus.UNLOCKED
