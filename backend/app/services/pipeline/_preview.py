"""Preview pipeline helpers — usados solo por scan-first flow gratis.

`run_preview_pipeline` (en orchestrator.py) corre un pipeline ligero que
solo consulta REPUVE. Los helpers aquí están separados del flow
principal para que orchestrator.py se quede compacto.
"""

import asyncio
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


_PREVIEW_REPUVE_TIMEOUT_SEC = 8.0


async def run_repuve_preview(
    plate: str | None, vin: str | None
) -> RepuveResult:
    """Wrapper resiliente de `repuve.query` para el preview pipeline.

    ## Por que timeout corto

    El sidecar REPUVE Vultr tiene timeout default de 120s (config
    `repuve_scraper_timeout_sec`) — apropiado para batch tools pero
    NO para el flow del scan inicial donde el user esta esperando ver
    su preview.

    Empiricamente (sesion 2026-05-03 telemetry) el sidecar tiene 0%
    hit rate por IP datacenter penalty del reCaptcha de Google, asi
    que esperar 120s NUNCA da un resultado positivo — solo bloquea
    al user 2 minutos hasta degradar a `captcha_required`.

    Mejor: timeout 8s (suficiente para el caso optimista donde Google
    esta lenient). Si no responde en 8s degradamos a `queried=False`
    y el frontend muestra el CTA al flow manual de subir screenshot
    del modal REPUVE (`RepuveScreenshotUploader`).

    UX antes: scan → 60-120s spinner "leyendo IA" → preview con
    captcha_required (mismo resultado que tendria en 8s).
    UX ahora: scan → ~10s spinner → preview con CTA inmediato.
    """
    try:
        return await asyncio.wait_for(
            repuve.query(plate=plate, vin=vin),
            timeout=_PREVIEW_REPUVE_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.info(
            "REPUVE preview timeout (%.0fs) — degradando a queried=False",
            _PREVIEW_REPUVE_TIMEOUT_SEC,
        )
        return RepuveResult(
            queried=False,
            plate=plate,
            vin=vin,
            raw_status="captcha_required",
            error=(
                "REPUVE solo permite consultas humanas — verificación "
                "oficial en 30s manuales abajo."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("REPUVE query fallo durante preview")
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
        # Tono intencional: el flow manual NO es un error técnico, es la
        # forma legal y segura de consultar REPUVE. La gente seria que
        # compra auto usado hace exactamente esto. Lo enmarcamos como
        # feature, no bug.
        return (
            f"Análisis preliminar: {score}/100. Verificación REPUVE "
            f"pendiente — toma 30 segundos completarla abajo (es el "
            f"método oficial que usan los compradores serios). Después "
            f"desbloquea el reporte completo con análisis IA de fotos, "
            f"comparativo de precio justo y revisión del anuncio."
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
