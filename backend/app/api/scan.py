"""Endpoints del flow scan-first (2026-05-01).

`POST /api/scan/plate` — entrada principal de la app. Recibe una foto
de la placa (base64) o el texto manual, hace OCR si hace falta, corre
el preview pipeline (solo REPUVE) y crea un `ReportRecord` con
`status=preview`. Devuelve `{report_id, plate, score, verdict, repuve}`.

El frontend redirige a `/preview/{report_id}` donde el usuario ve el
score visible y los demás campos blurred. El paywall (`/api/payments/
checkout`) acepta `report_id` y, tras confirmación de MP, el
background task corre `run_pipeline()` completo y reescribe el JSON
del mismo `ReportRecord` (status pasa a `unlocked`).

## Reusa REPUVE captcha-aware

`run_preview_pipeline` llama a `repuve.query()`, que ya tiene fallback
explícito: si Google reCaptcha no permite scrape automático devuelve
`queried=False, error="REPUVE pidió reCaptcha..."`. El frontend
muestra el aviso y el usuario igual puede seguir al pago — el unlock
se queda con la opción de REPUVE manual a futuro.
"""

import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.db.models import ReportRecord, ReportStatus
from app.db.session import SessionDep
from app.rate_limit import limiter
from app.services.pipeline import run_preview_pipeline
from app.services.smart_scanner import smart_scan

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scan"])

PREVIEW_TTL_HOURS = 24


class PlateScanRequest(BaseModel):
    """Body de `POST /api/scan/plate`.

    Una de tres modalidades (frontend elige):

    - `image_base64` + `media_type`: Claude OCR extrae la placa.
    - `manual_plate`: el usuario tipeó la placa (fallback sin cámara).
    - `manual_vin`: el usuario tipeó el VIN (algunos estados no usan placa).

    Si vienen multiples, prioridad: image > manual_plate > manual_vin.
    """

    image_base64: str | None = Field(
        default=None,
        min_length=100,
        description="Foto JPEG/PNG/WebP en base64",
    )
    media_type: Literal["image/jpeg", "image/png", "image/webp"] = Field(
        default="image/jpeg"
    )
    manual_plate: str | None = Field(default=None, max_length=16)
    manual_vin: str | None = Field(default=None, max_length=24)


class PlateScanResponse(BaseModel):
    """Respuesta del scan inicial — datos suficientes para el preview UI."""

    report_id: str
    plate: str | None
    vin: str | None
    score: int
    risk_level: str
    summary: str
    ocr_confidence: Literal["low", "medium", "high"] | None = None
    ocr_notes: str | None = None
    repuve: dict[str, Any]
    consultation_links: list[dict[str, Any]] = []
    # Smart scanner: tipo detectado cuando la imagen no era placa
    detected_type: Literal["plate", "vin", "invoice"] | None = None
    invoice_extra: dict[str, Any] | None = None


class SmartScanResponse(BaseModel):
    """Respuesta de `/api/scan/auto` — clasifica la imagen sin disparar
    todavía el pipeline preview. El frontend recibe el `type` detectado y
    decide si redirige a `/scan/plate` (con `manual_plate`/`manual_vin`)
    o a un flow distinto (futuro: `/scan/invoice` para Fase B+C).
    """

    type: Literal["plate", "vin", "invoice", "unknown"]
    value: str
    confidence: Literal["low", "medium", "high"]
    notes: str
    extra: dict[str, Any] = {}


@router.post("/scan/auto", response_model=SmartScanResponse)
@limiter.limit("30/minute")
async def scan_auto(
    request: Request, body: PlateScanRequest
) -> SmartScanResponse:
    """Smart scanner — clasifica la imagen sin disparar el pipeline.

    El usuario apunta la cámara a CUALQUIER cosa relevante (placa, VIN
    sticker, factura) y este endpoint devuelve qué detectó. El frontend
    decide qué flow seguir:

    - type=plate / vin → llamar `/scan/plate` con manual_plate / manual_vin
    - type=invoice → mostrar datos extraídos al usuario y opcionalmente
      pedirle escanear la placa o VIN para complementar
    - type=unknown → pedirle re-foto

    Costo: ~$0.005-0.008 USD por scan (single Claude call).
    """
    if not body.image_base64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Smart scan requiere image_base64",
        )
    try:
        result = await smart_scan(body.image_base64, body.media_type)
    except RuntimeError as exc:
        logger.exception("Smart scan falló")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No pude clasificar la imagen: {exc}",
        ) from exc

    return SmartScanResponse(
        type=result.type,
        value=result.value,
        confidence=result.confidence,
        notes=result.notes,
        extra=result.extra,
    )


@router.post("/scan/plate", response_model=PlateScanResponse)
@limiter.limit("30/minute")
async def scan_plate(
    request: Request, body: PlateScanRequest, session: SessionDep
) -> PlateScanResponse:
    """Resuelve la placa, corre preview pipeline y persiste ReportRecord."""
    plate, vin, ocr_conf, ocr_notes, detected_type, invoice_extra = (
        await _resolve_plate_and_vin(body)
    )
    if not plate and not vin:
        # Si smart scan detectó factura pero no placa/VIN, devolvemos
        # un response especial con detected_type=invoice para que el
        # frontend muestre los datos extraídos sin error.
        if detected_type == "invoice":
            return PlateScanResponse(
                report_id="",
                plate=None,
                vin=None,
                score=0,
                risk_level="yellow",
                summary=(
                    "Detecté que esta foto es una factura, no una placa "
                    "ni un VIN. Para verificar el auto necesito que también "
                    "escanees la placa o el NIV. La factura la podemos "
                    "validar después al desbloquear el reporte completo."
                ),
                repuve={"queried": False, "raw_status": "no_plate_provided"},
                detected_type="invoice",
                invoice_extra=invoice_extra,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No pude leer una placa ni un VIN. Re-toma la foto con "
                "más luz o ingresa la placa manualmente."
            ),
        )

    # MOD-018: ValueError del pipeline → 400 vía global handler en main.py
    report = await run_preview_pipeline(plate=plate, vin=vin)

    listing_hash = _hash_preview(plate=plate, vin=vin)
    record = ReportRecord(
        source_url=None,
        listing_hash=listing_hash,
        status=ReportStatus.PREVIEW,
        plate=plate,
        vin=vin,
        make=None,
        model=None,
        year=None,
        price_mxn=None,
        score=report.score,
        risk_level=report.risk_level.value,
        report_json=report.model_dump(mode="json"),
        expires_at=datetime.now(UTC) + timedelta(hours=PREVIEW_TTL_HOURS),
    )
    session.add(record)
    await session.flush()

    return PlateScanResponse(
        report_id=record.id,
        plate=plate,
        vin=vin,
        score=report.score,
        risk_level=report.risk_level.value,
        summary=report.summary,
        ocr_confidence=ocr_conf,
        ocr_notes=ocr_notes,
        repuve=report.repuve.model_dump(mode="json"),
        consultation_links=[
            link.model_dump(mode="json")
            for link in report.consultation_links
        ],
        detected_type=detected_type,
        invoice_extra=invoice_extra,
    )


# ---------------------------------------------------------------------------
# Helpers


async def _resolve_plate_and_vin(
    body: PlateScanRequest,
) -> tuple[
    str | None,
    str | None,
    Literal["low", "medium", "high"] | None,
    str | None,
    Literal["plate", "vin", "invoice"] | None,
    dict | None,
]:
    """Decide la fuente: foto (smart scanner) > placa manual > VIN manual.

    Devuelve `(plate, vin, confidence, notes, detected_type, invoice_extra)`.

    Cuando la imagen se procesa con smart scanner:
    - Si detecta `plate` → plate poblado, detected_type=plate
    - Si detecta `vin` → vin poblado, detected_type=vin
    - Si detecta `invoice` → ambos None pero invoice_extra con campos
    - Si detecta `unknown` → 400 con notas
    """
    if body.image_base64:
        try:
            result = await smart_scan(body.image_base64, body.media_type)
        except RuntimeError as exc:
            logger.exception("Smart scan falló")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"No pude procesar la imagen: {exc}",
            ) from exc

        if result.type == "plate" and result.value and 5 <= len(result.value) <= 7:
            return (
                result.value, None, result.confidence, result.notes,
                "plate", None,
            )
        if result.type == "vin" and result.value and len(result.value) == 17:
            return (
                None, result.value, result.confidence, result.notes,
                "vin", None,
            )
        if result.type == "invoice":
            # Factura detectada — devuelve invoice_extra para que el
            # caller maneje el flow especial (mostrar datos extraídos
            # y pedir escaneo de placa o VIN para complementar).
            return None, None, None, None, "invoice", result.extra

        # Unknown o validación fallida (placa muy corta, VIN no 17, etc.)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"No pude reconocer placa, VIN ni factura en la foto. "
                f"{result.notes} Re-toma la foto o ingresa los datos manualmente."
            ),
        )

    if body.manual_plate:
        plate = _normalize(body.manual_plate)
        if not (5 <= len(plate) <= 7):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La placa debe tener entre 5 y 7 caracteres alfanuméricos.",
            )
        return plate, None, None, None, None, None

    if body.manual_vin:
        vin = _normalize(body.manual_vin)
        if len(vin) != 17:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El VIN debe tener exactamente 17 caracteres alfanuméricos.",
            )
        return None, vin, None, None, None, None

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Se requiere image_base64, manual_plate o manual_vin.",
    )


def _normalize(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _hash_preview(plate: str | None, vin: str | None) -> str:
    payload = "|".join([plate or "", vin or ""]).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]
