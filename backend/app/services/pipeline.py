"""End-to-end pipeline. D2 wires the ML Motors scraper; D3-D7 plug in next.

Two entry points:

- ``run_pipeline(req)`` — full pipeline. Requiere `url` o `manual_listing`.
  Lo dispara el background task tras el pago confirmado (unlock).
- ``run_preview_pipeline(plate, vin)`` — pipeline ligero, solo REPUVE +
  scoring básico. No requiere listing. Se usa al escanear la placa
  para mostrar un preview gratis (scan-first flow, 2026-05-01).
"""

import asyncio
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
from app.analyzers import (
    description_analyzer,
    exif_analyzer,
    photo_analyzer,
    price_estimator,
    scoring,
    seller_analyzer,
    vin_check as vin_check_module,
)
from app.scrapers import mercadolibre, ml_search, repuve
from app.scrapers.multi_marketplace import find_cross_listings
from app.services.gob_mx_links import build_consultation_links
from app.services.photo_fetcher import fetch_photos

logger = logging.getLogger(__name__)


_PREVIEW_PLACEHOLDER_LISTING = ListingData(
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


async def run_preview_pipeline(
    plate: str | None = None, vin: str | None = None
) -> Report:
    """Pipeline ligero para el scan-first flow.

    Solo consulta REPUVE — no scrapea anuncio, no analiza fotos, no
    estima precio. Usa scoring estándar pero con listing placeholder,
    así que el score reflejará principalmente el resultado de REPUVE.

    Si REPUVE falla (reCaptcha) devolvemos el reporte igual con
    `repuve.queried=False` y un score conservador. La UI muestra el
    estado y el usuario puede pagar para que el unlock corra el
    pipeline completo (y, opcionalmente, REPUVE manual via captcha).
    """
    if not plate and not vin:
        raise ValueError("Se requiere placa o VIN para el preview")

    repuve_result = await _run_repuve(plate=plate, vin=vin)

    # Para el preview gratis incluimos los links de auto-verificación —
    # alto valor inmediato sin requerir saber la ubicación del auto
    # (los links federales y estatales aplican o no según el location
    # que tendremos al desbloquear).
    from app.models.report import ConsultationLinkModel

    raw_links = build_consultation_links(
        plate=plate, vin=vin, location=None
    )
    preview_links = [
        ConsultationLinkModel(
            name=l.name,
            url=l.url,
            description=l.description,
            category=l.category,
            applicable=l.applicable,
            state_scope=l.state_scope,
        )
        for l in raw_links
    ]

    report = Report(
        score=0,
        risk_level=RiskLevel.RED,
        summary="",
        listing=_PREVIEW_PLACEHOLDER_LISTING,
        repuve=repuve_result,
        price=PriceEstimate(comparables_count=0, sources=[]),
        photo_findings=[],
        description_findings=[],
        seller_findings=[],
        vin_check=None,
        consultation_links=preview_links,
        questions_for_seller=[],
    )
    report = scoring.populate(report)
    # Sin signal de REPUVE no podemos llamar verde a algo. El scoring
    # estándar daría 100/green (porque no hay penalty), pero eso induce
    # falsa confianza. Si REPUVE no respondió y no hay otra señal
    # negativa, capamos el preview a 50/yellow para conveyar "no
    # sabemos, hay que verificar manualmente".
    if not repuve_result.queried and report.risk_level == RiskLevel.GREEN:
        report.score = 50
        report.risk_level = RiskLevel.YELLOW
    report.summary = _build_preview_summary(report.score, report.risk_level, repuve_result)
    return report


def _build_preview_summary(
    score: int, risk: RiskLevel, repuve: RepuveResult
) -> str:
    """Summary específico del preview — explícito sobre qué SÍ se chequeó.

    El summary del scoring estándar narra el anuncio, pero en preview
    no hay anuncio. Aquí explicamos qué hicimos (REPUVE) y qué falta
    desbloquear (precio, fotos IA, descripción).
    """
    if repuve.is_stolen is True:
        return (
            f"🚨 ALERTA: REPUVE marca este vehículo como ROBADO. "
            f"Score: {score}/100. NO COMPRES ESTE AUTO."
        )
    if not repuve.queried:
        why = repuve.error or "REPUVE no respondió"
        return (
            f"Preview ({score}/100): REPUVE no se pudo consultar "
            f"automáticamente — {why} Desbloquea el reporte completo para "
            "que verifiquemos REPUVE manualmente, comparemos contra el "
            "precio justo del mercado y analicemos fotos del anuncio con IA."
        )
    if repuve.has_legal_status is False:
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


async def _run_repuve(
    plate: str | None, vin: str | None
) -> RepuveResult:
    """Wrapper resiliente de `repuve.query` para el preview pipeline."""
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


async def run_pipeline(req: AnalyzeRequest) -> Report:
    listing = await _resolve_listing(req)
    # REPUVE, precio, fotos (Claude vision), EXIF y cross-listings hacen I/O
    # — paralelizamos.
    repuve, price, photo_findings, exif_findings, cross_listings = (
        await asyncio.gather(
            _resolve_repuve(req),
            _resolve_price(listing),
            _resolve_photos(listing),
            _resolve_exif(listing),
            _resolve_cross_listings(listing),
        )
    )
    description_findings = description_analyzer.analyze(listing.description)
    seller_findings = seller_analyzer.analyze(listing)
    vin_check = await _maybe_run_vin_check(req, listing, repuve)
    consultation_links = _build_consultation_links_models(req, listing)

    report = Report(
        # Placeholder; `scoring.populate` lo sobreescribe a continuación.
        score=0,
        risk_level=RiskLevel.RED,
        summary="",
        listing=listing,
        repuve=repuve,
        price=price,
        photo_findings=photo_findings,
        exif_findings=exif_findings,
        description_findings=description_findings,
        seller_findings=seller_findings,
        vin_check=vin_check,
        consultation_links=consultation_links,
        cross_listings=cross_listings,
        questions_for_seller=[
            "¿Tienes la factura original y el endoso completo?",
            "¿Me dejas verificarlo en una agencia o con mi mecánico?",
            "¿Por qué lo vendes y desde cuándo lo tienes?",
        ],
    )
    return scoring.populate(report)


def _build_consultation_links_models(
    req: AnalyzeRequest, listing: ListingData
):
    """Genera los `ConsultationLinkModel` de portales gob.mx."""
    from app.models.report import ConsultationLinkModel

    raw_links = build_consultation_links(
        plate=req.plate,
        vin=req.vin,
        location=listing.location,
    )
    return [
        ConsultationLinkModel(
            name=link.name,
            url=link.url,
            description=link.description,
            category=link.category,
            applicable=link.applicable,
            state_scope=link.state_scope,
        )
        for link in raw_links
    ]


async def _maybe_run_vin_check(
    req: AnalyzeRequest, listing: ListingData, repuve: RepuveResult
):
    """Si la request trae VIN, corre el check enriquecido + integra al Report.

    Usa `check_with_enrichment` (async) que hace decode local + NHTSA vPIC
    en paralelo. Si NHTSA falla, degrada limpio al decode local.

    Si NO hay VIN escaneado pero la descripción del anuncio menciona
    uno, el `vin_check_module.check` lo extrae y lo regresa en
    `vin_in_description`. Por eso siempre vale la pena pasar el VIN
    cuando esté disponible.
    """
    if not req.vin:
        return None
    from app.models.report import (
        VinAlertModel,
        VinCheck,
        VinDecodedModel,
    )

    result = await vin_check_module.check_with_enrichment(
        raw_vin=req.vin,
        listing=listing,
        repuve=repuve,
    )

    decoded_kwargs = dict(result.decoded.__dict__)
    if result.nhtsa is not None and result.nhtsa.found:
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


async def _resolve_photos(listing: ListingData):
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


async def _resolve_cross_listings(listing: ListingData):
    """Busca el mismo make+model+year en otros marketplaces MX.

    Solo corre si tenemos make/model — sin eso no podemos buscar.
    Si todos los providers fallan, devuelve lista vacía sin tumbar
    el pipeline.
    """
    from app.models.report import CrossListingModel

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


async def _resolve_exif(listing: ListingData):
    """Descarga las fotos y extrae EXIF para detectar edición/duplicados.

    En la práctica las fotos de ML Motors vienen sin EXIF (el CDN la
    quita), entonces esto rinde más en upload manual. Si todas las
    descargas fallan, regresa lista vacía sin tumbar el pipeline.
    """
    from app.models.report import ExifFindingModel

    if not listing.photo_urls:
        return []
    try:
        bytes_list = await fetch_photos(listing.photo_urls[:6])
        metadatas = [exif_analyzer.extract_metadata(b) for b in bytes_list]
        findings = exif_analyzer.analyze_batch(
            metadatas, listing_year=listing.year
        )
        return [
            ExifFindingModel(
                photo_index=f.photo_index,
                flag=f.flag,
                severity=f.severity,
                note=f.note,
            )
            for f in findings
        ]
    except Exception:  # noqa: BLE001
        logger.exception("EXIF analyzer falló")
        return []
