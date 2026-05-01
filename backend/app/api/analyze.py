from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

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

router = APIRouter(tags=["analyze"])


def _to_pydantic_vin_check(result) -> VinCheck:
    """Convierte el dataclass `VinCheckResult` a su espejo Pydantic."""
    return VinCheck(
        decoded=VinDecodedModel(**result.decoded.__dict__),
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


@router.post("/vin/check", response_model=VinCheck)
async def check_vin(req: VinCheckRequest) -> VinCheck:
    """Decodifica un VIN escaneado y lo compara contra el anuncio.

    Usado por el frontend cuando el usuario escanea el VIN del auto
    físico. Devuelve marca/año decodificados + lista de alertas.

    Sin red, sin Claude API. Costo: cero.
    """
    result = vin_check_module.check(
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
