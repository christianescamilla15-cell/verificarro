"""Endpoint para parsear screenshots del modal REPUVE subidos por el usuario.

Flow mobile-first: el user abre repuve.gob.mx en el browser de su
celular, hace la consulta manual (resuelve el reCAPTCHA visible en
~5s), ve el modal con el resultado, toma una captura y la sube aqui.

Claude Vision OCR el texto del modal → pasa al parser canonico
(`parse_response`) → devuelve `RepuveResult` normalizado.

## Por que vs Chrome extension

Chrome extension solo cubre desktop (no existe en Chrome mobile) y
exige instalacion previa. El screenshot funciona en cualquier
dispositivo, sin instalacion. Costo marginal ~$0.005 USD por scan.

## NOTA: NO usar `from __future__ import annotations`

Combinacion `from __future__ import annotations` + Pydantic 2.9 +
FastAPI introspeccion de tipos causa `PydanticUndefinedAnnotation`
en runtime cuando el modelo Pydantic se referencia desde la firma
del endpoint. El error rompe el startup completo de la app.
Convencion del repo: los archivos en `app/api/` usan sintaxis
nativa Python 3.10+ sin el future import.
"""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.models.report import RepuveResult
from app.rate_limit import limiter
from app.scrapers.repuve import parse_response
from app.services.repuve_screenshot_ocr import (
    looks_like_repuve_text,
    scan_repuve_screenshot,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repuve", tags=["repuve-screenshot"])

# Limite tamao archivo. JPEG mobile ronda 200-800KB → en base64
# ~270K-1MB. PDF de REPUVE puede ser 1-2 MB → ~2-3MB en base64.
# Margen 4MB cubre ambos casos con holgura.
_MAX_IMAGE_B64_CHARS = 4_000_000


class ScreenshotRequest(BaseModel):
    """Body de `POST /api/repuve/screenshot`.

    Acepta imagen (cuando el user logra screenshot) o PDF (cuando el
    user usa el boton "Exportar a PDF" de REPUVE — necesario porque
    REPUVE bloquea screenshots con FLAG_SECURE en mobile).
    """

    plate: str | None = Field(default=None, max_length=16)
    vin: str | None = Field(default=None, max_length=24)
    image_base64: str = Field(
        min_length=100,
        description=(
            "Archivo del modal REPUVE en base64 — JPEG/PNG/WebP "
            "(captura) o PDF (exportado desde REPUVE)"
        ),
    )
    media_type: Literal[
        "image/jpeg", "image/png", "image/webp", "application/pdf"
    ] = Field(default="image/jpeg")
    source: str = Field(
        default="screenshot",
        max_length=64,
        description="Origen + version del client (e.g. 'mobile/0.1')",
    )


class ScreenshotResponse(BaseModel):
    queried: bool
    plate: str | None = None
    vin: str | None = None
    is_stolen: bool | None = None
    has_legal_status: bool | None = None
    raw_status: str | None = None
    error: str | None = None
    parser: Literal["screenshot_ocr"] = "screenshot_ocr"
    ocr_confidence: Literal["low", "medium", "high"] = "low"
    ocr_notes: str = ""


@router.post("/screenshot", response_model=ScreenshotResponse)
@limiter.limit("20/minute;120/hour")
async def screenshot_result(
    request: Request,
    body: ScreenshotRequest,
) -> ScreenshotResponse:
    if not body.plate and not body.vin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Falta placa o NIV",
        )

    if len(body.image_base64) > _MAX_IMAGE_B64_CHARS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Imagen excede limite "
                f"({len(body.image_base64)} > {_MAX_IMAGE_B64_CHARS} chars b64)"
            ),
        )

    logger.info(
        "repuve_screenshot source=%s plate=%s vin=%s image_b64_len=%d",
        body.source, body.plate, body.vin, len(body.image_base64),
    )

    try:
        ocr = await scan_repuve_screenshot(
            body.image_base64,
            media_type=body.media_type,
        )
    except RuntimeError as exc:
        # Falta API key o Claude no devolvio texto — error transitorio
        logger.warning("OCR REPUVE screenshot fallo: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de OCR temporalmente no disponible",
        ) from exc

    # Log estructurado para debug — crucial cuando el user reporta
    # "no leyo mi PDF" sabemos exactamente que devolvio Claude.
    logger.info(
        "repuve_ocr result: found_modal=%s confidence=%s text_len=%d notes=%r",
        ocr.found_modal, ocr.confidence, len(ocr.text), ocr.notes[:300],
    )

    # Caso 1: OCR no encontro modal → no llamamos parser, devolvemos
    # error claro para que el frontend pida re-tomar la foto.
    if not ocr.found_modal:
        return ScreenshotResponse(
            queried=False,
            plate=body.plate,
            vin=body.vin,
            error=(
                "No detectamos un modal REPUVE en la captura. "
                "Toma la foto despues de hacer clic en 'Buscar' y "
                "cuando aparezca el resultado en pantalla."
            ),
            raw_status="screenshot_no_modal",
            ocr_confidence=ocr.confidence,
            ocr_notes=ocr.notes,
        )

    # Caso 2: OCR encontro modal pero el texto no parece de REPUVE
    # (Claude pudo haberse confundido con otro sitio gob.mx).
    if not looks_like_repuve_text(ocr.text):
        return ScreenshotResponse(
            queried=False,
            plate=body.plate,
            vin=body.vin,
            error=(
                "La captura no parece ser del modal REPUVE oficial. "
                "Verifica que estes en repuve.gob.mx."
            ),
            raw_status="screenshot_not_repuve",
            ocr_confidence="low",
            ocr_notes=ocr.notes,
        )

    # Caso 3: parser canonico hace el resto. Pasamos el texto plano
    # — `parse_response()` corre `_strip_html` que es no-op si no hay
    # tags HTML, asi que funciona igual con texto puro.
    result: RepuveResult = parse_response(
        ocr.text,
        plate=body.plate,
        vin=body.vin,
        captcha_used=False,
    )

    return ScreenshotResponse(
        queried=result.queried,
        plate=result.plate,
        vin=result.vin,
        is_stolen=result.is_stolen,
        has_legal_status=result.has_legal_status,
        raw_status=result.raw_status,
        error=result.error,
        ocr_confidence=ocr.confidence,
        ocr_notes=ocr.notes,
    )


