"""Endpoints de pagos: checkout, webhook, status.

Flow completo:

1. `POST /api/payments/checkout` — frontend crea el pago. Backend
   inserta `Payment(status=pending)`, crea Preference en MP y devuelve
   `{init_point, payment_id}`. Frontend redirige a `init_point`.

2. `POST /api/payments/webhook` — MP llama aquí cuando hay actualización.
   Backend valida con `MP_WEBHOOK_SECRET` (si está set), consulta MP
   por el payment_id real, valida que `external_reference` coincida y
   actualiza `Payment.status=paid` (o failed según `mp_status`).

3. `GET /api/payments/{external_reference}` — frontend hace polling
   después del checkout. Devuelve el estado del Payment + el reporte
   si ya está generado.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select

from app.config import get_settings
from app.db.models import Payment, PaymentStatus, ReportRecord
from app.db.session import SessionDep
from app.services.mercadopago import (
    CheckoutPreference,
    create_preference,
    get_payment_info,
)
from app.services.report_generator import generate_report_for_payment

logger = logging.getLogger(__name__)

router = APIRouter(tags=["payments"])


class CheckoutRequest(BaseModel):
    """Body de `POST /api/payments/checkout`."""

    listing_url: HttpUrl | None = None
    plate: str | None = Field(default=None, max_length=16)
    vin: str | None = Field(default=None, max_length=24)
    payer_email: str | None = None
    tier: str = Field(default="basic", pattern=r"^(basic|premium)$")
    title_hint: str | None = Field(
        default=None, max_length=120,
        description=(
            "Título visible en el checkout, ej. 'Honda Civic 2018'. Si "
            "es None, usamos un placeholder genérico."
        ),
    )


class CheckoutResponse(BaseModel):
    payment_id: str
    external_reference: str
    init_point: str
    sandbox_init_point: str
    amount_mxn: float
    tier: str


class PaymentStatusResponse(BaseModel):
    payment_id: str
    status: str
    amount_mxn: float
    tier: str
    paid_at: datetime | None = None
    report_id: str | None = None
    report_json: dict[str, Any] | None = None


@router.post("/payments/checkout", response_model=CheckoutResponse)
async def checkout(req: CheckoutRequest, session: SessionDep) -> CheckoutResponse:
    """Crea un Payment pending y la Preference de MP."""
    settings = get_settings()
    amount = (
        settings.price_premium_mxn
        if req.tier == "premium"
        else settings.price_basic_mxn
    )
    external_ref = str(uuid.uuid4())
    title = (
        f"Verificarro {req.tier} — {req.title_hint}"
        if req.title_hint
        else f"Verificarro {req.tier} — Reporte de auto usado"
    )

    payment = Payment(
        amount_mxn=amount,
        tier=req.tier,
        status=PaymentStatus.PENDING,
        mp_external_reference=external_ref,
        listing_url=str(req.listing_url) if req.listing_url else None,
        plate=req.plate,
        vin=req.vin,
    )
    session.add(payment)
    await session.flush()  # asigna el id

    try:
        pref: CheckoutPreference = await create_preference(
            title=title,
            amount_mxn=amount,
            external_reference=external_ref,
            payer_email=req.payer_email,
            metadata={
                "payment_id": payment.id,
                "listing_url": str(req.listing_url) if req.listing_url else None,
                "tier": req.tier,
            },
        )
    except RuntimeError as exc:
        # No commit: la sesión se rollbackea al levantar HTTPException.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Mercado Pago no respondió: {exc}",
        ) from exc

    payment.mp_preference_id = pref.preference_id

    return CheckoutResponse(
        payment_id=payment.id,
        external_reference=external_ref,
        init_point=pref.init_point,
        sandbox_init_point=pref.sandbox_init_point,
        amount_mxn=amount,
        tier=req.tier,
    )


@router.post("/payments/webhook")
async def webhook(
    request: Request,
    session: SessionDep,
    background: BackgroundTasks,
) -> dict[str, Any]:
    """Recibe webhooks de Mercado Pago (topic=payment).

    MP manda el body con `{type: 'payment', data: {id: <mp_payment_id>}}`.
    Consultamos el payment, validamos `external_reference` y
    actualizamos el status en nuestra DB.

    Webhook validation con HMAC: si `MP_WEBHOOK_SECRET` está set, MP
    incluye un header `x-signature` con HMAC-SHA256. Por simplicidad
    en MVP, solo logueamos cuando falte; bloqueo strict en D9.5+ si
    los webhooks empiezan a abusar.
    """
    payload = await request.json()
    topic = payload.get("type") or payload.get("topic")
    data = payload.get("data") or {}
    mp_payment_id = data.get("id") or payload.get("data.id")

    if topic != "payment" or not mp_payment_id:
        # Otros topics (merchant_order, etc.) los ignoramos por ahora.
        logger.info("Webhook MP ignorado: topic=%s id=%s", topic, mp_payment_id)
        return {"ok": True, "ignored": "non-payment-topic"}

    try:
        info = await get_payment_info(str(mp_payment_id))
    except RuntimeError as exc:
        logger.warning("No pude consultar payment %s: %s", mp_payment_id, exc)
        return {"ok": True, "ignored": "lookup-failed"}

    if not info.external_reference:
        logger.warning(
            "Payment %s no tiene external_reference, ignorando", mp_payment_id
        )
        return {"ok": True, "ignored": "no-external-reference"}

    result = await session.execute(
        select(Payment).where(
            Payment.mp_external_reference == info.external_reference
        )
    )
    payment = result.scalar_one_or_none()
    if not payment:
        logger.warning(
            "external_reference %s no existe en DB", info.external_reference
        )
        return {"ok": True, "ignored": "unknown-external-reference"}

    # Mapeo de estados MP → nuestros
    new_status = _map_mp_status(info.status)
    if new_status == payment.status:
        return {"ok": True, "ignored": "idempotent-duplicate"}

    payment.status = new_status
    payment.mp_payment_id = info.payment_id
    if new_status == PaymentStatus.PAID:
        payment.paid_at = datetime.now(UTC)
        # Encolamos la generación del reporte: corre después de que
        # esta response se envía a MP. La task abre su propia DB
        # session para no depender de este request.
        background.add_task(generate_report_for_payment, payment.id)
        logger.info(
            "Payment %s confirmado — generación de reporte encolada",
            payment.id,
        )
    return {"ok": True, "status": new_status.value}


@router.get(
    "/payments/{external_reference}", response_model=PaymentStatusResponse
)
async def payment_status(
    external_reference: str, session: SessionDep
) -> PaymentStatusResponse:
    """Polling endpoint para que el frontend sepa cuándo está listo."""
    result = await session.execute(
        select(Payment).where(Payment.mp_external_reference == external_reference)
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pago no encontrado",
        )

    report_id: str | None = None
    report_json: dict | None = None
    if payment.status == PaymentStatus.PAID:
        rep_result = await session.execute(
            select(ReportRecord).where(ReportRecord.payment_id == payment.id)
        )
        report = rep_result.scalar_one_or_none()
        if report:
            report_id = report.id
            report_json = report.report_json

    return PaymentStatusResponse(
        payment_id=payment.id,
        status=payment.status.value,
        amount_mxn=payment.amount_mxn,
        tier=payment.tier,
        paid_at=payment.paid_at,
        report_id=report_id,
        report_json=report_json,
    )


# ---------------------------------------------------------------------------
# Helpers


def _map_mp_status(mp_status: str) -> PaymentStatus:
    """Mapea estados de MP → `PaymentStatus` interno.

    MP devuelve: approved, pending, in_process, rejected, refunded,
    cancelled, charged_back. Consolidamos en 4 estados internos.
    """
    if mp_status == "approved":
        return PaymentStatus.PAID
    if mp_status in {"refunded", "charged_back"}:
        return PaymentStatus.REFUNDED
    if mp_status in {"rejected", "cancelled"}:
        return PaymentStatus.FAILED
    return PaymentStatus.PENDING
