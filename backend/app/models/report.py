from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Source(str, Enum):
    MERCADOLIBRE = "mercadolibre"
    FACEBOOK = "facebook"
    MANUAL = "manual"


class RiskLevel(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class AnalyzeRequest(BaseModel):
    """Entrada del verificador.

    Para Mercado Libre Motors basta el `url`. Para Facebook Marketplace
    (requiere login) el frontend manda los campos manualmente vía
    `manual_listing` y opcionalmente fotos.

    REPUVE auto-consulta puede fallar por reCaptcha de Google. Para esos
    casos, el frontend ofrece un link a repuve.gob.mx y deja al usuario
    pegar el resultado en `repuve_manual`.

    `invoice_number` es opcional — número de factura original del auto.
    Cuando se provee, lo incluimos en el reporte como item de
    verificación obligatoria que el comprador debe pedir al vendedor.
    En Fase B agregamos OCR de la factura para cross-validar contra
    listing; en Fase C verificamos contra SAT.
    """

    url: HttpUrl | None = None
    plate: str | None = Field(default=None, description="Placa para REPUVE")
    vin: str | None = Field(default=None, description="NIV (VIN) para REPUVE")
    invoice_number: str | None = Field(
        default=None,
        max_length=64,
        description="Número de factura original del auto (folio o UUID CFDI)",
    )
    invoice_extra: dict | None = Field(
        default=None,
        description=(
            "Datos extraídos vía OCR del CFDI por el smart scanner: "
            "{folio_fiscal_uuid, rfc_emisor, rfc_receptor, fecha, total, "
            "marca, modelo, año, niv}. Usado para cross-validation contra "
            "el listing en `unlock_report_for_payment`."
        ),
    )
    source: Source = Source.MERCADOLIBRE
    manual_listing: "ManualListing | None" = None
    repuve_manual: "RepuveManual | None" = Field(
        default=None,
        description="Resultado de REPUVE pegado a mano cuando reCaptcha bloquea auto-consulta",
    )


class RepuveManual(BaseModel):
    """Resultado de REPUVE capturado manualmente por el usuario."""

    is_stolen: bool
    has_legal_status: bool | None = None
    notes: str = ""


class ManualListing(BaseModel):
    """Listado capturado a mano (FB Marketplace u otro sin scrape)."""

    title: str
    price_mxn: float
    year: int
    make: str
    model: str
    kilometers: int
    location: str
    description: str = ""
    seller_name: str = ""
    photo_urls: list[HttpUrl] = Field(default_factory=list)


class ListingData(BaseModel):
    """Anuncio normalizado tras scrape o captura manual."""

    source: Source
    source_url: str | None = None
    title: str
    price_mxn: float
    year: int
    make: str
    model: str
    trim: str | None = None
    kilometers: int
    location: str
    description: str = ""
    seller_name: str = ""
    seller_account_age_days: int | None = None
    # --- Trust signals adicionales del vendedor ML (2026-05-01) ---
    seller_sales_count: int | None = None
    seller_reputation: Literal["green", "yellow", "red", "unknown"] | None = None
    seller_other_listings_count: int | None = None
    seller_profile_url: str | None = None
    photo_urls: list[str] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=_utc_now)


class RepuveResult(BaseModel):
    queried: bool
    plate: str | None = None
    vin: str | None = None
    is_stolen: bool | None = None
    has_legal_status: bool | None = None
    raw_status: str | None = None
    error: str | None = None
    # scrape_stage = where in the pipeline this attempt ended.
    # Telemetry-only field — UI does not render it. Populated by the
    # scraper to support per-stage failure analysis (e.g. "are we
    # losing more attempts at WAF block-pre-captcha or at captcha
    # solve?"). Added 2026-05-03 as Quick Win #2 of the capture-rate
    # analysis.
    #
    # Vocabulary (extend cautiously; the analytics dashboard groups
    # on this exact string):
    #   - "success"                    — modal parsed, data returned
    #   - "page_load_failed"           — REPUVE_URL did not load
    #                                    (network / timeout / 5xx)
    #   - "selector_not_found"         — page loaded but the form
    #                                    inputs never appeared (likely
    #                                    WAF served a stripped page)
    #   - "captcha_widget_missing"     — form loaded but no reCaptcha
    #                                    widget rendered (WAF served
    #                                    page without anti-bot gate)
    #   - "captcha_solve_failed"       — 2Captcha / audio solver gave
    #                                    up before yielding a token
    #   - "captcha_token_rejected"     — token was submitted but REPUVE
    #                                    rejected it (token stale, IP
    #                                    mismatch, etc.)
    #   - "modal_empty"                — submit succeeded, modal opened,
    #                                    body was blank
    #   - "unhandled_exception"        — anything else in _run_query
    scrape_stage: str | None = None


class PriceEstimate(BaseModel):
    fair_price_mxn: float | None = None
    range_low_mxn: float | None = None
    range_high_mxn: float | None = None
    delta_pct: float | None = Field(
        default=None,
        description="(precio_anuncio - fair_price) / fair_price * 100",
    )
    comparables_count: int = 0
    sources: list[str] = Field(default_factory=list)


class PhotoFinding(BaseModel):
    photo_index: int
    issue: Literal[
        "paint_mismatch",
        "panel_gap",
        "rust",
        "prior_repair",
        "low_quality",
        "watermark_or_stock",
        "other",
    ]
    severity: Literal["low", "medium", "high"]
    note: str


class DescriptionFinding(BaseModel):
    flag: Literal[
        "urgency",
        "no_inspection_allowed",
        "seller_abroad",
        "advance_payment_request",
        "vague_history",
        "other",
    ]
    severity: Literal["low", "medium", "high"]
    excerpt: str


class CrossListingModel(BaseModel):
    """Listing del mismo auto encontrado en otro marketplace MX.

    Útil para detectar cross-postings (mismo vendedor anunciando en
    múltiples sitios — bandera media) o foto-stock revendida (mismo
    auto a precios MUY distintos = sospechoso).
    """

    marketplace: Literal[
        "vivanuncios", "seminuevos", "olx_mx", "fb_marketplace", "kavak",
    ]
    title: str
    price_mxn: float | None = None
    url: str
    location: str = ""
    photos: list[str] = Field(default_factory=list)
    seller_name: str = ""
    notes: str = ""


class ConsultationLinkModel(BaseModel):
    """Link a portal oficial gob.mx pre-llenado para que el usuario
    consulte él mismo. Espejo Pydantic del dataclass `ConsultationLink`
    de `app.services.gob_mx_links`."""

    name: str
    url: str
    description: str
    category: Literal["robo", "fiscal", "ambiental", "infracciones"]
    applicable: bool = True
    state_scope: str | None = None


class ExifFindingModel(BaseModel):
    """Hallazgo de la EXIF de una foto. Espejo Pydantic del dataclass
    `ExifFinding` de `app.analyzers.exif_analyzer`."""

    photo_index: int
    flag: Literal[
        "edited_software",
        "duplicate_timestamp",
        "old_photo",
        "no_exif_anywhere",
    ]
    severity: Literal["low", "medium", "high"]
    note: str


class SellerFinding(BaseModel):
    flag: Literal[
        "new_account",
        "no_other_listings",
        "low_response_rate",
        "duplicated_photos",
        "other",
    ]
    severity: Literal["low", "medium", "high"]
    note: str


class VinDecodedModel(BaseModel):
    """Resultado del decoder local del VIN + enrichment NHTSA (opcional).

    Los campos `nhtsa_*` se pueblan cuando NHTSA vPIC respondió. Si
    NHTSA falló o el VIN es inválido, vienen None y el reporte funciona
    igual con solo el decoder local.
    """

    vin: str
    valid_format: bool
    valid_checksum: bool
    wmi: str
    country: str | None = None
    manufacturer: str | None = None
    manufacturer_aliases: list[str] = Field(default_factory=list)
    year: int | None = None
    errors: list[str] = Field(default_factory=list)

    # --- Enrichment NHTSA vPIC (oficial) ---
    nhtsa_found: bool = False
    nhtsa_make: str | None = None
    nhtsa_model: str | None = None
    nhtsa_model_year: int | None = None
    nhtsa_body_class: str | None = None  # "Sedan", "SUV", "Pickup", ...
    nhtsa_trim: str | None = None
    nhtsa_engine_cylinders: int | None = None
    nhtsa_engine_displacement_l: float | None = None
    nhtsa_fuel_type: str | None = None
    nhtsa_transmission: str | None = None
    nhtsa_drive_type: str | None = None
    nhtsa_doors: int | None = None
    nhtsa_plant_country: str | None = None
    nhtsa_plant_city: str | None = None


class VinAlertModel(BaseModel):
    severity: Literal["low", "medium", "high"]
    message: str


class VinCheck(BaseModel):
    """Resultado de comparar el VIN escaneado contra el anuncio."""

    decoded: VinDecodedModel
    matches_listing: bool
    alerts: list[VinAlertModel] = Field(default_factory=list)
    vin_in_description: str | None = None
    scanned_at: datetime = Field(default_factory=_utc_now)


class VinCheckRequest(BaseModel):
    """Body de `POST /api/vin/check`."""

    vin: str = Field(min_length=10, max_length=24)
    listing: ListingData
    repuve: RepuveResult | None = None


class InvoiceData(BaseModel):
    """Datos de la factura del auto que el comprador DEBE pedir al vendedor.

    En Fase A (este commit) solo guardamos el `invoice_number` declarado
    por el comprador y el reporte instruye explícitamente que pida la
    factura original al vendedor antes de pagar. En Fase B agregamos
    OCR de la factura para extraer y cross-validar más campos. En Fase C
    consultamos SAT para validar que el CFDI exista y esté vigente.
    """

    invoice_number: str | None = None
    folio_fiscal_uuid: str | None = None  # CFDI UUID (Fase B)
    rfc_emisor: str | None = None  # Fase B
    rfc_receptor: str | None = None  # Fase B
    fecha: datetime | None = None  # Fase B
    total_mxn: float | None = None  # Fase B
    sat_status: Literal["vigente", "cancelado", "no_encontrado"] | None = None  # Fase C
    sat_checked_at: datetime | None = None  # Fase C
    notes: str = ""


class Report(BaseModel):
    score: int = Field(ge=0, le=100)
    risk_level: RiskLevel
    summary: str
    listing: ListingData
    repuve: RepuveResult
    price: PriceEstimate
    photo_findings: list[PhotoFinding] = Field(default_factory=list)
    exif_findings: list[ExifFindingModel] = Field(default_factory=list)
    description_findings: list[DescriptionFinding] = Field(default_factory=list)
    seller_findings: list[SellerFinding] = Field(default_factory=list)
    vin_check: VinCheck | None = None
    consultation_links: list[ConsultationLinkModel] = Field(default_factory=list)
    cross_listings: list[CrossListingModel] = Field(default_factory=list)
    invoice: InvoiceData | None = None
    questions_for_seller: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=_utc_now)


AnalyzeRequest.model_rebuild()
RepuveManual.model_rebuild()
VinCheck.model_rebuild()
VinCheckRequest.model_rebuild()
