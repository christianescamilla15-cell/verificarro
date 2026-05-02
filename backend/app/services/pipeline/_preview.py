"""Preview pipeline helpers — usados solo por scan-first flow gratis.

`run_preview_pipeline` (en orchestrator.py) corre un pipeline ligero que
solo consulta REPUVE. Los helpers aquí están separados del flow
principal para que orchestrator.py se quede compacto.
"""

import logging

from app.models.report import (
    ListingData,
    RepuveResult,
    RiskLevel,
    Source,
)
from app.scrapers import repuve

logger = logging.getLogger(__name__)


# Listing placeholder usado en preview — el pipeline normal espera
# `ListingData` populated, así que pasamos un stub válido pero vacío.
PREVIEW_PLACEHOLDER_LISTING = ListingData(
    source=Source.MANUAL,
    title="(escaneado por placa, sin anuncio)",
    price_mxn=0,
    year=0,
    make="",
    model="",
    kilometers=0,
    location="",
    description="",
    seller_name="",
    photo_urls=[],
)


async def run_repuve_preview(
    plate: str | None, vin: str | None
) -> RepuveResult:
    """Wrapper resiliente de `repuve.query` para el preview pipeline.

    Si REPUVE falla por reCaptcha u otra cosa, devolvemos
    `queried=False` con el error capturado. La UI muestra el aviso y
    el usuario igual puede pagar.
    """
    try:
        return await repuve.query(plate=plate, vin=vin)
    except Exception as exc:  # noqa: BLE001
        logger.exception("REPUVE query falló durante preview")
        return RepuveResult(
            queried=False,
            plate=plate,
            vin=vin,
            error=f"Error inesperado en REPUVE: {exc}",
        )


def build_preview_summary(
    score: int, risk: RiskLevel, repuve_result: RepuveResult,
) -> str:
    """Summary específico del preview — explícito sobre qué SÍ se chequeó.

    El summary del scoring estándar narra el anuncio, pero en preview
    no hay anuncio. Aquí explicamos qué hicimos (REPUVE) y qué falta
    desbloquear (precio, fotos IA, descripción).
    """
    if repuve_result.is_stolen is True:
        return (
            f"🚨 ALERTA: REPUVE marca este vehículo como ROBADO. "
            f"Score: {score}/100. NO COMPRES ESTE AUTO."
        )
    if not repuve_result.queried:
        why = repuve_result.error or "REPUVE no respondió"
        return (
            f"Preview ({score}/100): REPUVE no se pudo consultar "
            f"automáticamente — {why} Desbloquea el reporte completo para "
            "que verifiquemos REPUVE manualmente, comparemos contra el "
            "precio justo del mercado y analicemos fotos del anuncio con IA."
        )
    if repuve_result.has_legal_status is False:
        return (
            f"⚠️ Preview ({score}/100): REPUVE indica situación legal "
            "irregular. Desbloquea el reporte completo para ver detalles, "
            "comparar precio justo y revisar el anuncio."
        )
    if risk == RiskLevel.GREEN:
        return (
            f"✅ Preview ({score}/100): REPUVE no muestra reporte de robo. "
            "Desbloquea el reporte completo para verificar precio justo "
            "vs ~50 anuncios similares, análisis de fotos con IA y "
            "banderas en la descripción del vendedor."
        )
    return (
        f"Preview ({score}/100): hay puntos a revisar. Desbloquea el "
        "reporte completo para análisis del anuncio, precio justo, "
        "fotos con IA y más."
    )
