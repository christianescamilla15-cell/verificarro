import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.analyzers import vin_check as vin_check_module
from app.models.report import (
    AnalyzeRequest,
    Report,
    VinCheck,
    VinCheckRequest,
)
from app.rate_limit import limiter
from app.services.pdf_report import generate_pdf
from app.services.pipeline import run_pipeline
from app.services.pipeline.mappers import to_pydantic_vin_check
from app.services.vin_ocr import scan_vin_from_image

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analyze"])


class VinScanBody(BaseModel):
    """Body de `POST /api/vin/scan`."""

    image_base64: str = Field(min_length=100, description="Imagen JPEG/PNG en base64")
    media_type: Literal["image/jpeg", "image/png", "image/webp"] = Field(
        default="image/jpeg"
    )


class VinScanResponse(BaseModel):
    vin: str
    confidence: Literal["low", "medium", "high"]
    notes: str


@router.post("/analyze", response_model=Report)
@limiter.limit("10/minute;100/hour")  # H-1: hourly cap reduce drain Anthropic
async def analyze(request: Request, req: AnalyzeRequest) -> Report:
    # MOD-018: ValueError → 400 vía global handler en main.py.
    return await run_pipeline(req)


@router.post("/vin/scan", response_model=VinScanResponse)
@limiter.limit("30/minute;200/hour")  # H-1: hourly cap reduce drain Anthropic
async def scan_vin(request: Request, body: VinScanBody) -> VinScanResponse:
    """OCR de una foto del VIN del auto físico vía Claude visión.

    Flow del frontend:
    1. Usuario abre cámara, encuadra el VIN (tablero o marco de puerta)
    2. Frontend captura imagen, hace base64
    3. POST aquí → recibe {vin, confidence, notes}
    4. Si confidence==high y vin tiene 17 chars → frontend llama
       /api/vin/check para comparar contra el anuncio
    5. Si confidence<high → frontend pide al usuario re-escanear o
       capturar mejor

    Costo: ~$0.005 USD por escaneo. NO consume créditos del usuario,
    incluido en el reporte.
    """
    try:
        result = await scan_vin_from_image(body.image_base64, body.media_type)
    except RuntimeError as exc:
        logger.exception("VIN OCR falló")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No pude procesar la imagen: {exc}",
        ) from exc
    return VinScanResponse(
        vin=result.vin,
        confidence=result.confidence,
        notes=result.notes,
    )


@router.post("/vin/check", response_model=VinCheck)
@limiter.limit("30/minute")
async def check_vin(request: Request, req: VinCheckRequest) -> VinCheck:
    """Decodifica un VIN escaneado y lo compara contra el anuncio.

    Usado por el frontend cuando el usuario escanea el VIN del auto
    físico. Hace decode local + enrichment NHTSA vPIC en paralelo:
    si NHTSA responde, se incluyen specs oficiales fabricante (body
    class, engine, doors, plant country) y alertas de discrepancia.

    Costos:
    - Decoder local: $0
    - NHTSA vPIC: $0 (gratis, sin auth, sin rate limit publicado)
    - Si NHTSA falla → degradación limpia al decoder local

    Latencia típica: <100ms si NHTSA falla, ~1.5s si responde.
    """
    result = await vin_check_module.check_with_enrichment(
        raw_vin=req.vin,
        listing=req.listing,
        repuve=req.repuve,
    )
    return to_pydantic_vin_check(result)


@router.post("/analyze/pdf")
@limiter.limit("10/minute")
async def analyze_to_pdf(request: Request, report: Report) -> Response:
    """Convierte un `Report` JSON ya analizado a PDF descargable.

    El frontend llama primero a `/analyze` (JSON), muestra el reporte
    interactivo, y cuando el usuario quiere descargar invoca este
    endpoint con el mismo Report — así el análisis NO corre dos veces.
    """
    pdf_bytes = generate_pdf(report)
    fname = f"verificarro-{report.listing.year or 'reporte'}-{report.score}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
