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

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.db.models import ReportRecord, ReportStatus
from app.db.session import SessionDep
from app.services.pipeline import run_preview_pipeline
from app.services.plate_ocr import scan_plate_from_image

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


@router.post("/scan/plate", response_model=PlateScanResponse)
async def scan_plate(
    body: PlateScanRequest, session: SessionDep
) -> PlateScanResponse:
    """Resuelve la placa, corre preview pipeline y persiste ReportRecord."""
    plate, vin, ocr_conf, ocr_notes = await _resolve_plate_and_vin(body)
    if not plate and not vin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No pude leer una placa ni un VIN. Re-toma la foto con "
                "más luz o ingresa la placa manualmente."
            ),
        )

    try:
        report = await run_preview_pipeline(plate=plate, vin=vin)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

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
    )


# ---------------------------------------------------------------------------
# Helpers


async def _resolve_plate_and_vin(
    body: PlateScanRequest,
) -> tuple[str | None, str | None, Literal["low", "medium", "high"] | None, str | None]:
    """Decide la fuente: foto (OCR) > placa manual > VIN manual."""
    if body.image_base64:
        try:
            scan = await scan_plate_from_image(body.image_base64, body.media_type)
        except RuntimeError as exc:
            logger.exception("Plate OCR falló")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"No pude procesar la imagen: {exc}",
            ) from exc
        if not scan.plate:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"No pude leer la placa en la foto. {scan.notes} "
                    "Re-toma la foto o ingresa la placa manualmente."
                ),
            )
        return scan.plate, None, scan.confidence, scan.notes

    if body.manual_plate:
        plate = _normalize(body.manual_plate)
        if not (5 <= len(plate) <= 7):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La placa debe tener entre 5 y 7 caracteres alfanuméricos.",
            )
        return plate, None, None, None

    if body.manual_vin:
        vin = _normalize(body.manual_vin)
        if len(vin) != 17:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El VIN debe tener exactamente 17 caracteres alfanuméricos.",
            )
        return None, vin, None, None

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Se requiere image_base64, manual_plate o manual_vin.",
    )


def _normalize(s: str) -> str:
    import re

    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _hash_preview(plate: str | None, vin: str | None) -> str:
    payload = "|".join([plate or "", vin or ""]).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]
