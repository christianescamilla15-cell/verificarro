"""End-to-end pipeline. D1 returns a stub; D2-D7 will plug in real modules."""

from app.models.report import (
    AnalyzeRequest,
    ListingData,
    PriceEstimate,
    Report,
    RepuveResult,
    RiskLevel,
    Source,
)


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

    # D2 connects this branch to the real Mercado Libre Motors scraper.
    return ListingData(
        source=Source.MERCADOLIBRE,
        source_url=str(req.url),
        title="(scraper pendiente — D2)",
        price_mxn=0,
        year=0,
        make="",
        model="",
        kilometers=0,
        location="",
    )


async def _resolve_repuve(req: AnalyzeRequest) -> RepuveResult:
    if not req.plate and not req.vin:
        return RepuveResult(queried=False, error="Sin placa ni NIV")
    # D3 will run the actual REPUVE Playwright scraper.
    return RepuveResult(
        queried=False,
        plate=req.plate,
        vin=req.vin,
        error="REPUVE scraper pendiente — D3",
    )


async def _resolve_price(_listing: ListingData) -> PriceEstimate:
    # D4 plugs in the Kavak / Seminuevos comparable scraper.
    return PriceEstimate(comparables_count=0, sources=[])
