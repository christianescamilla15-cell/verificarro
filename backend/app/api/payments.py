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

import hashlib
import hmac
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select

from app.api.auth import get_optional_user
from app.config import Settings, get_settings
from app.db.models import Payment, PaymentStatus, ReportRecord, ReportStatus, User
from app.db.session import SessionDep
from app.rate_limit import limiter
from app.services.mercadopago import (
    CheckoutPreference,
    PreapprovalResult,
    create_preapproval,
    create_preference,
    get_payment_info,
    get_preapproval_info,
)
from app.services.report_generator import (
    generate_report_for_payment,
    unlock_report_for_payment,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["payments"])

# DI shortcut para inyectar Settings en endpoints (MOD-017)
SettingsDep = Annotated[Settings, Depends(get_settings)]


class CheckoutRequest(BaseModel):
    """Body de `POST /api/payments/checkout`.

    Dos modos:

    - **Scan-first (preferido)**: el frontend pasa `report_id` del
      preview ya creado por `/api/scan/plate`. Backend lo enlaza con
      este Payment y, al confirmar, el webhook reescribe ese mismo
      ReportRecord con el reporte completo.
    - **Legacy**: si NO viene `report_id` (e.g. flow antiguo de URL +
      email manual), backend acepta `listing_url`/`plate`/`vin`
      directos y genera un nuevo Report tras el pago.
    """

    report_id: str | None = Field(
        default=None,
        max_length=36,
        description="ID del ReportRecord preview creado por /api/scan/plate",
    )
    listing_url: HttpUrl | None = None
    plate: str | None = Field(default=None, max_length=16)
    vin: str | None = Field(default=None, max_length=24)
    invoice_number: str | None = Field(default=None, max_length=64)
    payer_email: str | None = None
    # 4 tiers:
    #   basic   $49  — single report con análisis completo
    #   premium $99  — basic + soporte WhatsApp
    #   search  $199 — pase 30 días, hasta 50 reportes (búsqueda activa)
    #   dealer  $1499 — pase 30 días, hasta 500 reportes (lotero)
    tier: str = Field(default="basic", pattern=r"^(basic|premium|search|dealer)$")
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
    polling_token: str  # MOD-005: requerido en GET /payments/{ref}


class PaymentStatusResponse(BaseModel):
    payment_id: str
    status: str
    amount_mxn: float
    tier: str
    paid_at: datetime | None = None
    report_id: str | None = None
    report_status: str | None = None  # preview | unlocked
    report_json: dict[str, Any] | None = None


@router.post("/payments/checkout", response_model=CheckoutResponse)
@limiter.limit("10/minute")
async def checkout(
    request: Request,
    req: CheckoutRequest,
    session: SessionDep,
    settings: SettingsDep,
    current_user: Annotated[User | None, Depends(get_optional_user)] = None,
) -> CheckoutResponse:
    """Crea un Payment pending y la Preference de MP.

    Si `report_id` viene set, hidrata `plate`/`vin` desde ese preview
    Report y enlaza Payment ↔ Report (bidireccional).

    ### Auth (defense-in-depth)

    Endpoint **anónimo by-design** para preservar el funnel scan-first
    (un usuario nuevo no debe tener que registrarse antes de pagar su
    primer reporte). Si el caller manda Bearer JWT válido, persistimos
    `user_id` en la fila Payment para que aparezca después en su
    /dashboard. Sin token, el Payment queda huérfano hasta que el user
    se registre con el mismo email (matching por email es trabajo
    futuro — ver MOD-038).
    """
    amount = _amount_for_tier(req.tier, settings)
    external_ref = str(uuid.uuid4())

    preview_report: ReportRecord | None = None
    plate = req.plate
    vin = req.vin
    if req.report_id:
        result = await session.execute(
            select(ReportRecord).where(ReportRecord.id == req.report_id)
        )
        preview_report = result.scalar_one_or_none()
        if not preview_report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Reporte preview {req.report_id} no existe",
            )
        if preview_report.status == ReportStatus.UNLOCKED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Este reporte ya está desbloqueado",
            )
        # Snapshot plate/vin del preview al Payment
        plate = plate or preview_report.plate
        vin = vin or preview_report.vin

    title = (
        f"Verificarro {req.tier} — {req.title_hint}"
        if req.title_hint
        else f"Verificarro {req.tier} — Reporte de auto usado"
    )

    payment = Payment(
        user_id=current_user.id if current_user else None,
        amount_mxn=amount,
        tier=req.tier,
        status=PaymentStatus.PENDING,
        mp_external_reference=external_ref,
        listing_url=str(req.listing_url) if req.listing_url else None,
        plate=plate,
        vin=vin,
        invoice_number=req.invoice_number.strip() if req.invoice_number else None,
        payer_email=req.payer_email.strip() if req.payer_email else None,
    )
    session.add(payment)
    await session.flush()  # asigna el id

    # Linkamos preview Report → Payment (idempotente, mismo ID si re-checkout)
    if preview_report is not None:
        preview_report.payment_id = payment.id

    try:
        pref: CheckoutPreference = await create_preference(
            title=title,
            amount_mxn=amount,
            external_reference=external_ref,
            payer_email=req.payer_email,
            metadata={
                "payment_id": payment.id,
                "report_id": req.report_id,
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
        polling_token=_make_polling_token(payment.id, external_ref),
    )


class SubscribeRequest(BaseModel):
    """Body de `POST /api/payments/subscribe` — tier mensual real con
    MP preapproval.

    Solo válido para tier `search` ($199/mes) y `dealer` ($1499/mes).
    Para tier basic/premium (one-time) usar `/api/payments/checkout`.
    """

    tier: str = Field(pattern=r"^(search|dealer)$")
    payer_email: str = Field(min_length=5, max_length=255)
    name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=32)


class SubscribeResponse(BaseModel):
    preapproval_id: str
    init_point: str
    external_reference: str
    amount_mxn: float
    tier: str
    polling_token: str  # MOD-005: para futuras consultas de status
    activation_note: str  # MOD-007: status comunicado al frontend


@router.post("/payments/subscribe", response_model=SubscribeResponse)
@limiter.limit("10/minute")
async def subscribe(
    request: Request,
    req: SubscribeRequest,
    session: SessionDep,
    settings: SettingsDep,
    current_user: Annotated[User | None, Depends(get_optional_user)] = None,
) -> SubscribeResponse:
    """Crea una suscripción mensual real con MP preapproval.

    Diferente a `/api/payments/checkout` (one-time payment): este crea
    un preapproval que MP cobra automáticamente cada mes hasta que el
    usuario cancele.

    ### Persistencia (MOD-013)

    Insertamos un `Payment` row con `status=pending` y `tier=search|dealer`
    al crear el preapproval. Cuando MP autorice (vía webhook
    `topic=preapproval` con `status=authorized`), el handler de webhook
    actualiza ese mismo row a `status=paid`. Esto permite que el
    dashboard del usuario refleje correctamente cuando su plan está
    activo y cuándo expira.
    """
    amount = _amount_for_tier(req.tier, settings)

    reason_label = "Búsqueda activa" if req.tier == "search" else "Dealer / Lotero"
    reason = f"Verificarro {reason_label} — {req.tier}"

    try:
        result: PreapprovalResult = await create_preapproval(
            reason=reason,
            amount_mxn=amount,
            payer_email=req.payer_email.strip(),
            frequency=1,
            frequency_type="months",
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No pudimos crear la suscripción: {exc}",
        ) from exc

    # MOD-013: persistir Payment para que el webhook de preapproval pueda
    # encontrarlo por external_reference y actualizarlo cuando MP
    # autorice / pause / cancele.
    # MOD-038: si hay JWT, asociamos user_id para que la subscripción
    # aparezca en /dashboard. Sin JWT, queda huérfano (igual que checkout).
    payment = Payment(
        user_id=current_user.id if current_user else None,
        amount_mxn=amount,
        tier=req.tier,
        status=PaymentStatus.PENDING,
        mp_external_reference=result.external_reference,
        mp_preference_id=result.preapproval_id,  # reusamos col para
                                                  # almacenar preapproval_id
        payer_email=req.payer_email.strip(),
    )
    session.add(payment)
    await session.flush()

    logger.info(
        "[SUBSCRIBE-CREATED] preapproval=%s payment=%s tier=%s email=%s "
        "amount=%s — esperando webhook preapproval para activar",
        result.preapproval_id, payment.id, req.tier, req.payer_email, amount,
    )

    return SubscribeResponse(
        preapproval_id=result.preapproval_id,
        init_point=result.init_point,
        external_reference=result.external_reference,
        amount_mxn=amount,
        tier=req.tier,
        polling_token=_make_polling_token(
            result.preapproval_id, result.external_reference,
        ),
        activation_note=(
            "Tu plan se activa cuando Mercado Pago confirme el primer "
            "cobro. Recibirás email con tus credenciales en menos de 1 "
            "hora hábil. Si tarda más, escríbenos por WhatsApp."
        ),
    )


@router.post("/payments/webhook")
@limiter.limit("60/minute")
async def webhook(
    request: Request,
    session: SessionDep,
    background: BackgroundTasks,
) -> dict[str, Any]:
    """Recibe webhooks de Mercado Pago (topic=payment).

    MP manda el body con `{type: 'payment', data: {id: <mp_payment_id>}}`.
    Consultamos el payment, validamos `external_reference` y
    actualizamos el status en nuestra DB.

    ### HMAC validation

    Si `MP_WEBHOOK_SECRET` está configurado, validamos `x-signature`
    contra el manifest oficial de MP:

        manifest = "id:<data.id>;request-id:<x-request-id>;ts:<ts>;"
        expected = hmac_sha256(MP_WEBHOOK_SECRET, manifest)

    Si la firma falla → `401 Unauthorized`. Sin esto, cualquiera con la
    URL puede POSTear webhooks fake y disparar `unlock_report_for_payment`
    para liberar reportes ajenos.

    Backward-compat: si `MP_WEBHOOK_SECRET` está vacío (config dev/MVP),
    NO validamos — solo loggeamos warning. Cutover a strict cuando se
    setee el secret en Render.
    """
    payload = await request.json()
    topic = payload.get("type") or payload.get("topic")
    data = payload.get("data") or {}
    mp_id = data.get("id") or payload.get("data.id")

    # HMAC check ANTES de cualquier procesamiento. Si la firma es mala,
    # ni siquiera consultamos a MP por el ID (evita amplification).
    if not _verify_mp_signature(request, mp_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook signature inválida",
        )

    # MOD-013: branch para topic=preapproval (suscripciones search/dealer)
    if topic == "preapproval" and mp_id:
        return await _handle_preapproval_webhook(str(mp_id), session)

    if topic != "payment" or not mp_id:
        # Otros topics (merchant_order, etc.) los ignoramos por ahora.
        logger.info("Webhook MP ignorado: topic=%s id=%s", topic, mp_id)
        return {"ok": True, "ignored": "non-payment-topic"}

    try:
        info = await get_payment_info(str(mp_id))
    except RuntimeError as exc:
        logger.warning("No pude consultar payment %s: %s", mp_id, exc)
        return {"ok": True, "ignored": "lookup-failed"}

    if not info.external_reference:
        logger.warning(
            "Payment %s no tiene external_reference, ignorando", mp_id
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
        # Encolamos generación. Si el Payment está enlazado con un
        # preview Report (scan-first flow) reescribimos ese registro;
        # si no hay preview (legacy), creamos un ReportRecord nuevo.
        has_preview = await _payment_has_preview(session, payment.id)
        task = (
            unlock_report_for_payment if has_preview
            else generate_report_for_payment
        )
        background.add_task(task, payment.id)
        logger.info(
            "Payment %s confirmado — %s encolado",
            payment.id, task.__name__,
        )
    return {"ok": True, "status": new_status.value}


async def _handle_preapproval_webhook(
    preapproval_id: str, session,
) -> dict[str, Any]:
    """Handler para `topic=preapproval` (MOD-013).

    MP llama aquí cuando cambia el ciclo de vida de una suscripción
    (search/dealer):
    - `authorized`: usuario completó el flow en MP y autorizó cobros.
       → status del Payment local pasa a PAID, paid_at = now.
    - `paused`: el cobro recurrente está pausado (usuario o MP).
       → status pasa a PENDING (esperando reanudar) — TODO: estado más
       específico si lo necesitamos en el dashboard.
    - `cancelled`: cancelación definitiva.
       → status pasa a FAILED. Frontend mostrará "tu suscripción
       terminó" en el dashboard.
    - `pending`: aún sin autorizar (estado inicial post-create_preapproval).
       → no-op, esperamos siguiente webhook.

    Idempotente: dos webhooks consecutivos con mismo status → no-op.
    """
    try:
        info = await get_preapproval_info(preapproval_id)
    except RuntimeError as exc:
        logger.warning(
            "No pude consultar preapproval %s: %s", preapproval_id, exc,
        )
        return {"ok": True, "ignored": "lookup-failed"}

    if not info.external_reference:
        logger.warning(
            "Preapproval %s no tiene external_reference, ignorando",
            preapproval_id,
        )
        return {"ok": True, "ignored": "no-external-reference"}

    # Buscamos el Payment row creado en /subscribe (mp_external_reference
    # matchea el del preapproval).
    result = await session.execute(
        select(Payment).where(
            Payment.mp_external_reference == info.external_reference
        )
    )
    payment = result.scalar_one_or_none()
    if not payment:
        logger.warning(
            "Preapproval external_reference %s no existe en DB",
            info.external_reference,
        )
        return {"ok": True, "ignored": "unknown-external-reference"}

    new_status = _map_preapproval_status(info.status)
    if new_status == payment.status:
        return {"ok": True, "ignored": "idempotent-duplicate"}

    payment.status = new_status
    if new_status == PaymentStatus.PAID:
        payment.paid_at = datetime.now(UTC)
        logger.info(
            "[PREAPPROVAL-AUTHORIZED] payment=%s tier=%s email=%s "
            "amount=%s — plan activo, mandar credenciales por email",
            payment.id, payment.tier, payment.payer_email, payment.amount_mxn,
        )
        # TODO: agregar background task para mandar email de bienvenida
        # con instrucciones de uso del plan. Por ahora el log es señal
        # operacional; Christian puede mandar el email manualmente
        # desde la integración Resend hasta que automaticemos.

    return {"ok": True, "preapproval_status": info.status, "payment_status": new_status.value}


def _map_preapproval_status(mp_status: str) -> PaymentStatus:
    """Mapea estados de MP preapproval → `PaymentStatus` interno."""
    if mp_status == "authorized":
        return PaymentStatus.PAID
    if mp_status == "cancelled":
        return PaymentStatus.FAILED
    # pending, paused → mantenemos PENDING (no tenemos estado dedicado
    # para "paused"; cuando el dashboard lo necesite se agrega).
    return PaymentStatus.PENDING


async def _payment_has_preview(session, payment_id: str) -> bool:
    """True si el Payment tiene un ReportRecord preview enlazado."""
    result = await session.execute(
        select(ReportRecord.id).where(
            ReportRecord.payment_id == payment_id,
            ReportRecord.status == ReportStatus.PREVIEW,
        )
    )
    return result.scalar_one_or_none() is not None


@router.get(
    "/payments/{external_reference}", response_model=PaymentStatusResponse
)
async def payment_status(
    external_reference: str,
    session: SessionDep,
    token: str | None = None,
) -> PaymentStatusResponse:
    """Polling endpoint para que el frontend sepa cuándo está listo.

    ### Auth (MOD-005)

    Requiere `?token=<polling_token>` que el frontend recibió en la
    response de `/checkout` o `/subscribe`. El token es un HMAC del
    `payment_id + external_reference`, validado stateless. Sin esto,
    cualquiera con el `external_reference` (UUIDv4 opaco pero filtrable
    en referer headers, browser history, screenshots compartidos) podía
    leer el `report_json` completo con PII (payer_email, plate, VIN).
    """
    result = await session.execute(
        select(Payment).where(Payment.mp_external_reference == external_reference)
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pago no encontrado",
        )

    expected = _make_polling_token(payment.id, external_reference)
    if not token or not hmac.compare_digest(expected, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Polling token inválido o ausente",
        )

    report_id: str | None = None
    report_status: str | None = None
    report_json: dict | None = None
    rep_result = await session.execute(
        select(ReportRecord).where(ReportRecord.payment_id == payment.id)
    )
    report = rep_result.scalar_one_or_none()
    if report:
        report_id = report.id
        report_status = report.status.value
        # Solo entregamos el JSON completo cuando el reporte está unlocked.
        # Mientras esté preview, el frontend ya tiene el preview localmente
        # y debe esperar a que el background task termine el upgrade.
        if report.status == ReportStatus.UNLOCKED:
            report_json = report.report_json

    return PaymentStatusResponse(
        payment_id=payment.id,
        status=payment.status.value,
        amount_mxn=payment.amount_mxn,
        tier=payment.tier,
        paid_at=payment.paid_at,
        report_id=report_id,
        report_status=report_status,
        report_json=report_json,
    )


# ---------------------------------------------------------------------------
# Helpers


def _make_polling_token(payment_id: str, external_reference: str) -> str:
    """HMAC-SHA256 stateless del payment_id + external_reference.

    Usado por `/payments/{ref}?token=X` para validar que solo el cliente
    que originó el checkout puede consultar el status (que incluye PII).

    Recompute en cada request — no se almacena en DB. Si JWT_SECRET rota,
    los tokens viejos invalidan automáticamente (esperado: el frontend
    pierde polling de un Payment muy viejo, pero ya están unlocked vía
    email transaccional).
    """
    settings = get_settings()
    msg = f"{payment_id}:{external_reference}".encode("utf-8")
    return hmac.new(
        settings.jwt_secret.encode("utf-8"),
        msg,
        hashlib.sha256,
    ).hexdigest()[:32]


def _amount_for_tier(tier: str, settings) -> float:
    """Resuelve el precio MXN del tier solicitado."""
    return {
        "basic": settings.price_basic_mxn,
        "premium": settings.price_premium_mxn,
        "search": settings.price_search_mxn,
        "dealer": settings.price_dealer_mxn,
    }.get(tier, settings.price_basic_mxn)


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


def _verify_mp_signature(request: Request, mp_payment_id: Any) -> bool:
    """Valida `x-signature` HMAC-SHA256 contra el manifest oficial de MP.

    Header format: `x-signature: ts=<ts>,v1=<hex_hmac>`
    Manifest: `id:<data.id>;request-id:<x-request-id>;ts:<ts>;`
        (los segmentos opcionales se omiten si su valor es vacío)

    Si `MP_WEBHOOK_SECRET` está vacío, NO validamos (modo dev/MVP) y
    devolvemos True con un warning. Cuando se setee el secret en Render
    el modo cambia a strict automáticamente.
    """
    settings = get_settings()
    secret = settings.mp_webhook_secret.strip()
    if not secret:
        logger.warning(
            "MP_WEBHOOK_SECRET vacío — webhook signature NO validada. "
            "Cualquiera con la URL puede mandar webhooks fake. "
            "Configurar en Render para activar HMAC strict."
        )
        return True

    sig_header = request.headers.get("x-signature", "")
    if not sig_header:
        logger.warning("Webhook MP sin x-signature header — rechazando")
        return False

    # Parse "ts=...,v1=..." en cualquier orden
    parts: dict[str, str] = {}
    for chunk in sig_header.split(","):
        if "=" not in chunk:
            continue
        k, v = chunk.split("=", 1)
        parts[k.strip()] = v.strip()
    ts = parts.get("ts")
    v1 = parts.get("v1")
    if not ts or not v1:
        logger.warning("Webhook MP signature malformada: %s", sig_header)
        return False

    request_id = request.headers.get("x-request-id", "")
    payment_id = str(mp_payment_id) if mp_payment_id else ""

    # MP omite segmentos opcionales con valor vacío del manifest. Solo
    # incluimos los que tienen valor para que el HMAC matchee el de MP.
    segments: list[str] = []
    if payment_id:
        segments.append(f"id:{payment_id};")
    if request_id:
        segments.append(f"request-id:{request_id};")
    segments.append(f"ts:{ts};")
    manifest = "".join(segments)

    expected = hmac.new(
        secret.encode("utf-8"),
        manifest.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, v1):
        logger.warning(
            "Webhook MP HMAC mismatch — manifest=%s expected=%s got=%s",
            manifest, expected[:8] + "...", v1[:8] + "...",
        )
        return False

    return True
