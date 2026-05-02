"""I/O step runners del pipeline completo — paralelizables vía asyncio.gather.

Cada `_resolve_*` resuelve UN aspecto del reporte (listing scrape, REPUVE,
precio, fotos, EXIF, cross-listings) y es failure-tolerant: si falla, log
+ retorna un valor vacío/sentinel en lugar de tumbar todo el pipeline.

`run_pipeline` (orchestrator.py) los corre en paralelo con `asyncio.gather`
y compone el `Report` final con los resultados.
"""

import logging

from app.analyzers import (
    exif_analyzer,
    photo_analyzer,
    price_estimator,
)
from app.models.report import (
    AnalyzeRequest,
    CrossListingModel,
    ExifFindingModel,
    ListingData,
    PriceEstimate,
    RepuveResult,
    Source,
)
from app.scrapers import mercadolibre, ml_search, repuve
from app.scrapers.multi_marketplace import find_cross_listings
from app.services.photo_fetcher import fetch_photos

logger = logging.getLogger(__name__)


async def resolve_listing(req: AnalyzeRequest) -> ListingData:
    """Devuelve el ListingData a partir de manual_listing o scrape de URL.

    Si la URL es de Mercado Libre, scrapea con `mercadolibre.scrape`.
    Si trae manual_listing, lo convierte directo a ListingData.
    Cualquier otra source con URL → ValueError (Vivanuncios/Seminuevos
    requieren manual hoy).
    """
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


async def resolve_repuve(req: AnalyzeRequest) -> RepuveResult:
    """Consulta REPUVE oficial. Failure tolerant.

    Tres modos:
    1. `repuve_manual` set → usuario ya consultó manual, eso gana
    2. Sin plate ni VIN → no podemos consultar, retorna queried=False
    3. Default: scrape repuve.gob.mx con captcha-aware fallback
    """
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


async def resolve_price(listing: ListingData) -> PriceEstimate:
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


async def resolve_photos(listing: ListingData):
    """Analiza las primeras N fotos con Claude visión.

    Si no hay fotos o la API key falta, regresa lista vacía. Cualquier
    error individual lo absorbe `photo_analyzer` (no propaga).
    """
    if not listing.photo_urls:
        return []
    try:
        return await photo_analyzer.analyze_photos(listing.photo_urls)
    except Exception:  # noqa: BLE001
        logger.exception("Photo analyzer falló")
        return []


async def resolve_cross_listings(listing: ListingData) -> list[CrossListingModel]:
    """Busca el mismo make+model+year en otros marketplaces MX.

    Solo corre si tenemos make/model — sin eso no podemos buscar.
    Si todos los providers fallan, devuelve lista vacía sin tumbar
    el pipeline.
    """
    if not listing.make or not listing.model:
        return []

    try:
        result = await find_cross_listings(
            make=listing.make,
            model=listing.model,
            year=listing.year if listing.year > 0 else None,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Multi-marketplace search falló")
        return []

    return [
        CrossListingModel(
            marketplace=cl.marketplace,
            title=cl.title,
            price_mxn=cl.price_mxn,
            url=cl.url,
            location=cl.location,
            photos=cl.photos,
            seller_name=cl.seller_name,
            notes=cl.notes,
        )
        for cl in result.listings
    ]


async def resolve_exif(listing: ListingData) -> list[ExifFindingModel]:
    """Descarga las fotos y extrae EXIF para detectar edición/duplicados.

    En la práctica las fotos de ML Motors vienen sin EXIF (el CDN la
    quita), entonces esto rinde más en upload manual. Si todas las
    descargas fallan, regresa lista vacía sin tumbar el pipeline.

    MOD-016: el analyzer regresa directamente `ExifFindingModel` (Pydantic).
    Antes había un mapper inline aquí que duplicaba campos del dataclass
    al espejo Pydantic — ya no es necesario.
    """
    if not listing.photo_urls:
        return []
    try:
        bytes_list = await fetch_photos(listing.photo_urls[:6])
        metadatas = [exif_analyzer.extract_metadata(b) for b in bytes_list]
        return exif_analyzer.analyze_batch(
            metadatas, listing_year=listing.year
        )
    except Exception:  # noqa: BLE001
        logger.exception("EXIF analyzer falló")
        return []
