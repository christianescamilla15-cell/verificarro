"""Pipeline orchestrator — entry points públicos.

Dos flujos:

- `run_preview_pipeline(plate, vin)` — pipeline ligero, solo REPUVE.
  Usado al escanear placa (gratis) para mostrar preview con score base.

- `run_pipeline(req)` — full pipeline post-pago. Paraleliza listing
  scrape + REPUVE + precio + fotos + EXIF + cross-listings con
  `asyncio.gather`, luego compone Pydantic `Report` final.

Toda la lógica de IO vive en `steps.py`. Los mappers Pydantic en
`mappers.py`. Invoice/CFDI en `invoice.py`. Helpers preview en
`_preview.py`. Esto se queda chico y leíble.
"""

import asyncio
import logging

from app.analyzers import description_analyzer, scoring, seller_analyzer
from app.analyzers.invoice_validator import validate_invoice_against_listing
from app.models.report import (
    AnalyzeRequest,
    ConsultationLinkModel,
    DescriptionFinding,
    PriceEstimate,
    Report,
    RiskLevel,
)
from app.services.gob_mx_links import build_consultation_links
from app.services.pipeline._preview import (
    PREVIEW_PLACEHOLDER_LISTING,
    build_preview_summary,
    run_repuve_preview,
)
from app.services.pipeline.invoice import (
    build_invoice_data_with_verification,
    build_questions_for_seller,
)
from app.services.pipeline.mappers import (
    build_consultation_links_models,
    maybe_run_vin_check,
)
from app.services.pipeline.steps import (
    resolve_cross_listings,
    resolve_exif,
    resolve_listing,
    resolve_photos,
    resolve_price,
    resolve_repuve,
)

logger = logging.getLogger(__name__)


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

    repuve_result = await run_repuve_preview(plate=plate, vin=vin)

    # Para el preview gratis incluimos los links de auto-verificación —
    # alto valor inmediato sin requerir saber la ubicación del auto.
    raw_links = build_consultation_links(plate=plate, vin=vin, location=None)
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
        listing=PREVIEW_PLACEHOLDER_LISTING,
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
    # negativa, capamos el preview a 50/yellow.
    if not repuve_result.queried and report.risk_level == RiskLevel.GREEN:
        report.score = 50
        report.risk_level = RiskLevel.YELLOW
    report.summary = build_preview_summary(
        report.score, report.risk_level, repuve_result,
    )
    return report


async def run_pipeline(req: AnalyzeRequest) -> Report:
    """Pipeline completo post-pago. Paraleliza I/O y compone Report final.

    Steps que corren en `asyncio.gather` (paralelizados):
    - REPUVE consulta
    - Precio justo (ML Motors comparables)
    - Fotos analyzer (Claude vision)
    - EXIF metadata
    - Cross-listings (Vivanuncios + Seminuevos)

    Luego (secuencial, son sync o dependen de listing/repuve):
    - Description analyzer
    - Seller analyzer
    - VIN check (si hay VIN)
    - Consultation links
    - Invoice data + SAT verify
    - Cross-validación factura vs listing
    """
    listing = await resolve_listing(req)

    repuve, price, photo_findings, exif_findings, cross_listings = (
        await asyncio.gather(
            resolve_repuve(req),
            resolve_price(listing),
            resolve_photos(listing),
            resolve_exif(listing),
            resolve_cross_listings(listing),
        )
    )

    description_findings = description_analyzer.analyze(listing.description)
    seller_findings = seller_analyzer.analyze(listing)
    vin_check = await maybe_run_vin_check(req, listing, repuve)
    consultation_links = build_consultation_links_models(req, listing)
    invoice_data = await build_invoice_data_with_verification(req)

    # Cross-validación factura vs listing (Fase B). Solo agrega findings,
    # no muta nada más.
    if req.invoice_extra:
        invoice_findings = validate_invoice_against_listing(
            req.invoice_extra,
            listing_make=listing.make,
            listing_model=listing.model,
            listing_year=listing.year,
            scanned_vin=req.vin,
        )
        for f in invoice_findings:
            description_findings.append(DescriptionFinding(
                flag="vague_history",
                severity=f.severity,
                excerpt=f.message,
            ))

    # Findings adicionales por SAT verify (Fase C) — si invoice_data
    # tiene sat_status, traducimos a finding según gravedad.
    if invoice_data and invoice_data.sat_status:
        if invoice_data.sat_status == "cancelado":
            description_findings.append(DescriptionFinding(
                flag="vague_history",
                severity="high",
                excerpt=(
                    f"SAT confirma que la factura (UUID "
                    f"{invoice_data.folio_fiscal_uuid}) está CANCELADA. "
                    "El dueño previo la canceló — verifica por qué con el vendedor."
                ),
            ))
        elif invoice_data.sat_status == "no_encontrado":
            description_findings.append(DescriptionFinding(
                flag="vague_history",
                severity="high",
                excerpt=(
                    f"SAT NO ENCUENTRA la factura con UUID "
                    f"{invoice_data.folio_fiscal_uuid}. Posible factura "
                    "falsa/inventada — fraude documental obvio."
                ),
            ))

    report = Report(
        # Placeholders; `scoring.populate` los sobreescribe abajo.
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
        invoice=invoice_data,
        questions_for_seller=build_questions_for_seller(invoice_data),
    )
    return scoring.populate(report)
