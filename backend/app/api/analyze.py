from fastapi import APIRouter, HTTPException, status

from app.models.report import AnalyzeRequest, Report
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
