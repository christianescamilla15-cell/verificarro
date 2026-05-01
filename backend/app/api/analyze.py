import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.analyzers import vin_check as vin_check_module
from app.models.report import (
    AnalyzeRequest,
    Report,
    VinAlertModel,
    VinCheck,
    VinCheckRequest,
    VinDecodedModel,
)
from app.services.pdf_report import generate_pdf
from app.services.pipeline import run_pipeline
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


def _to_pydantic_vin_check(result) -> VinCheck:
    """Convierte el dataclass `VinCheckResult` a su espejo Pydantic.

    Si `result.nhtsa` está set (vino enrichment), inyecta los campos
    NHTSA al `VinDecodedModel` para que el frontend los muestre.
    """
    decoded_kwargs = dict(result.decoded.__dict__)
    if getattr(result, "nhtsa", None) is not None and result.nhtsa.found:
        n = result.nhtsa
        decoded_kwargs.update({
            "nhtsa_found": True,
            "nhtsa_make": n.make,
            "nhtsa_model": n.model,
            "nhtsa_model_year": n.model_year,
            "nhtsa_body_class": n.body_class,
            "nhtsa_trim": n.trim,
            "nhtsa_engine_cylinders": n.engine_cylinders,
            "nhtsa_engine_displacement_l": n.engine_displacement_l,
            "nhtsa_fuel_type": n.fuel_type_primary,
            "nhtsa_transmission": n.transmission_style,
            "nhtsa_drive_type": n.drive_type,
            "nhtsa_doors": n.doors,
            "nhtsa_plant_country": n.plant_country,
            "nhtsa_plant_city": n.plant_city,
        })
    return VinCheck(
        decoded=VinDecodedModel(**decoded_kwargs),
        matches_listing=result.matches_listing,
        alerts=[VinAlertModel(severity=a.severity, message=a.message)
                for a in result.alerts],
        vin_in_description=result.vin_in_description,
        scanned_at=result.scanned_at,
    )


@router.post("/analyze", response_model=Report)
async def analyze(req: AnalyzeRequest) -> Report:
    try:
        return await run_pipeline(req)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.post("/vin/scan", response_model=VinScanResponse)
async def scan_vin(body: VinScanBody) -> VinScanResponse:
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
async def check_vin(req: VinCheckRequest) -> VinCheck:
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
    return _to_pydantic_vin_check(result)


@router.post("/analyze/pdf")
async def analyze_to_pdf(report: Report) -> Response:
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
