from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from app.models.report import AnalyzeRequest, Report
from app.services.pdf_report import generate_pdf
from app.services.pipeline import run_pipeline

router = APIRouter(tags=["analyze"])


@router.post("/analyze", response_model=Report)
async def analyze(req: AnalyzeRequest) -> Report:
    try:
        return await run_pipeline(req)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


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
