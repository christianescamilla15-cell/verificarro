"""Mercado Pago integration: create Preference + parse webhook.

Wrapper delgado sobre el SDK oficial `mercadopago` (no async — corremos
en un threadpool con `asyncio.to_thread` para no bloquear el event loop).

## Flow del checkout

1. Frontend llama `POST /api/payments/checkout` con
   `{listing_url, plate?, vin?, tier?}`.
2. Backend crea un `Payment` row en estado `pending` con
   `mp_external_reference=<uuid>`.
3. `create_preference()` aquí pide a MP una Preference Item con título,
   monto y URLs de retorno. MP devuelve `init_point` (URL para pagar).
4. Backend guarda `mp_preference_id` en el Payment y devuelve
   `{init_point, payment_id}` al frontend.
5. Frontend redirige al usuario a `init_point`.
6. Usuario paga en MP (OXXO, SPEI, tarjeta).
7. MP envía webhook a `POST /api/payments/webhook` con
   `topic=payment&id=<mp_payment_id>`.
8. Backend pide detalles del pago a MP, valida `external_reference`,
   actualiza `Payment.status=paid` y dispara la generación del
   reporte.

## Modos: producción vs test

`MP_ACCESS_TOKEN` empieza con `TEST-` en sandbox o `APP_USR-` en
producción. El SDK no distingue — usa el token que le des.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckoutPreference:
    """Resultado de crear una Preference en Mercado Pago."""

    preference_id: str
    init_point: str  # URL para redirigir al usuario al checkout
    sandbox_init_point: str  # URL test mode
    external_reference: str


@dataclass(frozen=True)
class MpPaymentInfo:
    """Detalle de un pago consultado a la API de MP."""

    payment_id: str
    status: str  # 'approved' | 'pending' | 'rejected' | 'cancelled' | ...
    status_detail: str
    external_reference: str | None
    transaction_amount: float | None


@dataclass(frozen=True)
class PreapprovalResult:
    """Resultado de crear un preapproval (suscripción mensual) en MP.

    `init_point` es la URL donde el usuario autoriza el cargo recurrente.
    Una vez autoriza, MP cobra automáticamente cada periodo y manda
    webhook a nuestro `/api/payments/webhook` con topic=preapproval.
    """

    preapproval_id: str
    init_point: str
    external_reference: str
    status: str  # 'pending' | 'authorized' | 'paused' | 'cancelled'


def _get_sdk():
    """Lazy import del SDK para que tests sin token no fallen al importar."""
    import mercadopago

    settings = get_settings()
    if not settings.mp_access_token:
        raise RuntimeError(
            "MP_ACCESS_TOKEN no configurado. Configúralo en .env o exporta "
            "como variable de entorno antes de invocar este servicio."
        )
    return mercadopago.SDK(settings.mp_access_token)


async def create_preference(
    *,
    title: str,
    amount_mxn: float,
    external_reference: str | None = None,
    payer_email: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> CheckoutPreference:
    """Crea una Preference de checkout. Wraps el call sync del SDK.

    Args:
        title: descripción que aparece en el checkout (ej. "Verificarro
            básico — Honda Civic 2018").
        amount_mxn: monto en pesos mexicanos (puede tener decimales).
        external_reference: nuestro UUID local para vincular el webhook
            con el `Payment` row. Si None, generamos uno.
        payer_email: email del pagador (si lo conocemos, MP pre-llena el
            checkout).
        metadata: dict opcional con info extra (listing URL, etc.).

    Returns:
        `CheckoutPreference` con `init_point` para redirigir al usuario.
    """
    settings = get_settings()
    ext_ref = external_reference or str(uuid.uuid4())

    body: dict[str, Any] = {
        "items": [{
            "title": title[:256],
            "quantity": 1,
            "currency_id": "MXN",
            "unit_price": float(amount_mxn),
        }],
        "external_reference": ext_ref,
        "back_urls": {
            "success": settings.mp_success_url,
            "failure": settings.mp_failure_url,
            "pending": settings.mp_pending_url,
        },
        "auto_return": "approved",
        "statement_descriptor": "VERIFICARRO",
        # Métodos de pago: tarjeta + efectivo (OXXO) + transferencia (SPEI)
        "payment_methods": {
            "excluded_payment_types": [],
            "installments": 12,
        },
    }
    if payer_email:
        body["payer"] = {"email": payer_email}
    if metadata:
        body["metadata"] = metadata

    def _sync_create() -> dict[str, Any]:
        sdk = _get_sdk()
        return sdk.preference().create(body)

    try:
        response = await asyncio.to_thread(_sync_create)
    except Exception as exc:
        logger.exception("MP preference creation failed")
        raise RuntimeError(f"No pude crear la preferencia de pago: {exc}") from exc

    if response.get("status") not in (200, 201):
        raise RuntimeError(
            f"MP API rechazó la preferencia: status={response.get('status')} "
            f"body={response.get('response')}"
        )

    pref = response["response"]
    return CheckoutPreference(
        preference_id=pref["id"],
        init_point=pref["init_point"],
        sandbox_init_point=pref.get("sandbox_init_point", pref["init_point"]),
        external_reference=ext_ref,
    )


async def create_preapproval(
    *,
    reason: str,
    amount_mxn: float,
    payer_email: str,
    external_reference: str | None = None,
    frequency: int = 1,
    frequency_type: str = "months",
) -> PreapprovalResult:
    """Crea un preapproval (suscripción recurrente) en Mercado Pago.

    Una vez autorizado por el usuario en el `init_point`, MP cobra
    automáticamente cada periodo según `frequency_type`. Webhook con
    topic=preapproval llega cuando el estado cambia (autorizado /
    pausado / cancelado).

    Args:
        reason: descripción visible al usuario en el checkout
        amount_mxn: monto a cobrar cada periodo
        payer_email: email del subscriptor (MP necesita dueño)
        external_reference: nuestro UUID local opcional
        frequency: número de unidades (1 = mensual)
        frequency_type: "months" o "days"
    """
    settings = get_settings()
    if not settings.mp_access_token:
        raise RuntimeError(
            "MP_ACCESS_TOKEN no configurado. Configúralo en .env o exporta "
            "como variable de entorno antes de invocar este servicio."
        )

    ext_ref = external_reference or str(uuid.uuid4())

    payload = {
        "reason": reason,
        "external_reference": ext_ref,
        "payer_email": payer_email,
        "auto_recurring": {
            "frequency": frequency,
            "frequency_type": frequency_type,
            "transaction_amount": float(amount_mxn),
            "currency_id": "MXN",
        },
        "back_url": settings.mp_success_url,
        "status": "pending",  # MP setea a authorized cuando el user firma
    }

    def _sync_create() -> dict[str, Any]:
        sdk = _get_sdk()
        return sdk.preapproval().create(payload)

    try:
        response = await asyncio.to_thread(_sync_create)
    except Exception as exc:  # noqa: BLE001
        logger.exception("MP preapproval create failed")
        raise RuntimeError(f"No pude crear la suscripción: {exc}") from exc

    if response.get("status") not in (200, 201):
        raise RuntimeError(
            f"MP devolvió error al crear preapproval: "
            f"status={response.get('status')}, "
            f"detail={response.get('response')}"
        )

    pre = response["response"]
    return PreapprovalResult(
        preapproval_id=pre["id"],
        init_point=pre["init_point"],
        external_reference=ext_ref,
        status=pre.get("status", "pending"),
    )


@dataclass(frozen=True)
class MpPreapprovalInfo:
    """Detalle de un preapproval consultado a la API de MP.

    Se usa en el webhook handler para `topic=preapproval` cuando MP
    notifica cambios en el ciclo de vida de la suscripción (autorización
    inicial, pausa, cancelación, fallo de cobro).
    """

    preapproval_id: str
    status: str  # 'pending' | 'authorized' | 'paused' | 'cancelled'
    external_reference: str | None
    payer_email: str | None
    transaction_amount: float | None
    next_payment_date: str | None  # ISO 8601 string si MP lo provee


async def get_preapproval_info(mp_preapproval_id: str) -> MpPreapprovalInfo:
    """Consulta el detalle de un preapproval (suscripción) vía MP API.

    Usado en webhook con topic=preapproval. MP cambia el status del
    preapproval cuando:
    - `authorized`: usuario completó el flujo en MP y autorizó.
    - `paused`: el usuario o MP pausó el cargo recurrente.
    - `cancelled`: el usuario o MP canceló definitivamente.
    """

    def _sync_get() -> dict[str, Any]:
        sdk = _get_sdk()
        return sdk.preapproval().get(mp_preapproval_id)

    try:
        response = await asyncio.to_thread(_sync_get)
    except Exception as exc:
        logger.exception("MP preapproval lookup failed")
        raise RuntimeError(
            f"No pude consultar la suscripción en MP: {exc}"
        ) from exc

    if response.get("status") not in (200, 201):
        raise RuntimeError(
            f"MP devolvió error al consultar preapproval "
            f"{mp_preapproval_id}: status={response.get('status')}"
        )

    p = response["response"]
    return MpPreapprovalInfo(
        preapproval_id=str(p["id"]),
        status=p.get("status", "unknown"),
        external_reference=p.get("external_reference"),
        payer_email=p.get("payer_email"),
        transaction_amount=(
            p.get("auto_recurring", {}).get("transaction_amount")
        ),
        next_payment_date=p.get("next_payment_date"),
    )


async def get_payment_info(mp_payment_id: str) -> MpPaymentInfo:
    """Consulta el detalle de un pago vía la API de MP. Usado en webhook."""

    def _sync_get() -> dict[str, Any]:
        sdk = _get_sdk()
        return sdk.payment().get(mp_payment_id)

    try:
        response = await asyncio.to_thread(_sync_get)
    except Exception as exc:
        logger.exception("MP payment lookup failed")
        raise RuntimeError(f"No pude consultar el pago en MP: {exc}") from exc

    if response.get("status") not in (200, 201):
        raise RuntimeError(
            f"MP devolvió error al consultar payment {mp_payment_id}: "
            f"status={response.get('status')}"
        )

    p = response["response"]
    return MpPaymentInfo(
        payment_id=str(p["id"]),
        status=p.get("status", "unknown"),
        status_detail=p.get("status_detail", ""),
        external_reference=p.get("external_reference"),
        transaction_amount=p.get("transaction_amount"),
    )
