"""End-to-end pipeline. D2 wires the ML Motors scraper; D3-D7 plug in next."""

import logging

from app.models.report import (
    AnalyzeRequest,
    ListingData,
    PriceEstimate,
    Report,
    RepuveResult,
    RiskLevel,
    Source,
)
from app.analyzers import price_estimator
from app.scrapers import mercadolibre, ml_search, repuve

logger = logging.getLogger(__name__)


async def run_pipeline(req: AnalyzeRequest) -> Report:
    listing = await _resolve_listing(req)
    repuve = await _resolve_repuve(req)
    price = await _resolve_price(listing)

    return Report(
        score=50,
        risk_level=RiskLevel.YELLOW,
        summary=(
            "Reporte placeholder — el motor de análisis se conectará en D2-D7. "
            "Por ahora solo se valida la entrada y se devuelve el anuncio "
            "normalizado."
        ),
        listing=listing,
        repuve=repuve,
        price=price,
        questions_for_seller=[
            "¿Tienes la factura original y el endoso completo?",
            "¿Me dejas verificarlo en una agencia o con mi mecánico?",
            "¿Por qué lo vendes y desde cuándo lo tienes?",
        ],
    )


async def _resolve_listing(req: AnalyzeRequest) -> ListingData:
    if req.manual_listing is not None:
        ml = req.manual_listing
        return ListingData(
            source=req.source,
            source_url=str(req.url) if req.url else None,
            title=ml.title,
            price_mxn=ml.price_mxn,
            year=ml.year,
            make=ml.make,
            model=ml.model,
            kilometers=ml.kilometers,
            location=ml.location,
            description=ml.description,
            seller_name=ml.seller_name,
            photo_urls=[str(u) for u in ml.photo_urls],
        )

    if req.url is None:
        raise ValueError(
            "Se requiere `url` (Mercado Libre) o `manual_listing` (Facebook)."
        )

    if req.source == Source.MERCADOLIBRE:
        try:
            return await mercadolibre.scrape(str(req.url))
        except ValueError:
            raise
        except Exception as exc:
            logger.exception("Mercado Libre scrape falló")
            raise ValueError(
                f"No pude leer el anuncio de Mercado Libre: {exc}"
            ) from exc

    raise ValueError(
        f"Source `{req.source}` requiere `manual_listing` (no soporta URL directa)."
    )


async def _resolve_repuve(req: AnalyzeRequest) -> RepuveResult:
    # 1. Si el usuario ya pegó el resultado manualmente, eso gana.
    if req.repuve_manual is not None:
        return RepuveResult(
            queried=True,
            plate=req.plate,
            vin=req.vin,
            is_stolen=req.repuve_manual.is_stolen,
            has_legal_status=req.repuve_manual.has_legal_status,
            raw_status="manual",
        )

    if not req.plate and not req.vin:
        return RepuveResult(queried=False, error="Sin placa ni NIV")

    try:
        return await repuve.query(plate=req.plate, vin=req.vin)
    except Exception as exc:  # noqa: BLE001
        logger.exception("REPUVE query falló")
        return RepuveResult(
            queried=False,
            plate=req.plate,
            vin=req.vin,
            error=f"Error inesperado en REPUVE: {exc}",
        )


async def _resolve_price(listing: ListingData) -> PriceEstimate:
    """Trae comparables de ML Motors search y calcula precio justo."""
    if not listing.make or not listing.model:
        return PriceEstimate(comparables_count=0, sources=[])

    try:
        comparables = await ml_search.find_comparables(
            listing.make, listing.model, limit=50
        )
    except Exception:  # noqa: BLE001
        logger.exception("ML search comparables falló")
        return PriceEstimate(comparables_count=0, sources=[])

    return price_estimator.estimate(
        listing, comparables, sources=["mercadolibre"]
    )
