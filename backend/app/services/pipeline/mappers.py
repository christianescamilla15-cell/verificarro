"""Pydantic conversion helpers — wrap dataclass-style results en
modelos Pydantic finales del Report.

Estos NO hacen I/O (excepto `maybe_run_vin_check` que llama NHTSA, pero
también está aquí porque su output es un VinCheck Pydantic que requiere
mapping). Mover a steps.py implica que steps.py importe Pydantic models
de report.py, mezclando capas.

MOD-015 elimina la duplicación de `_to_pydantic_vin_check` que existía
también en `app.api.analyze`. Ahora vive aquí solo y `analyze.py` la
importa.
"""

import logging

from app.analyzers import vin_check as vin_check_module
from app.models.report import (
    AnalyzeRequest,
    ConsultationLinkModel,
    ListingData,
    RepuveResult,
    VinAlertModel,
    VinCheck,
    VinDecodedModel,
)
from app.services.gob_mx_links import build_consultation_links

logger = logging.getLogger(__name__)


def to_pydantic_vin_check(result) -> VinCheck:
    """Convierte un `vin_check.CheckResult` (dataclass) a `VinCheck` Pydantic.

    Si el resultado trae enrichment NHTSA, los campos `nhtsa_*` del
    `VinDecodedModel` se popula desde el resultado; si no, quedan None.

    Se llama tanto desde el pipeline (post-resolve VIN) como desde
    `/api/vin/check` directo (sin pipeline). Antes existía duplicado en
    ambos sitios — MOD-015 lo unifica aquí.
    """
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


async def maybe_run_vin_check(
    req: AnalyzeRequest, listing: ListingData, repuve_result: RepuveResult,
) -> VinCheck | None:
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

    result = await vin_check_module.check_with_enrichment(
        raw_vin=req.vin,
        listing=listing,
        repuve=repuve_result,
    )
    return to_pydantic_vin_check(result)


def build_consultation_links_models(
    req: AnalyzeRequest, listing: ListingData,
) -> list[ConsultationLinkModel]:
    """Wrapper thin de `build_consultation_links()` con args del request.

    MOD-016: post-conversion del dataclass `ConsultationLink` → Pydantic
    `ConsultationLinkModel` en gob_mx_links.py, este wrapper ya no
    convierte — solo orquesta los args desde `req` + `listing`. Lo
    mantenemos por DRY: orchestrator + (futuros callers) llaman a
    una función con la firma del request en lugar de extraer
    plate/vin/location en cada sitio.
    """
    return build_consultation_links(
        plate=req.plate,
        vin=req.vin,
        location=listing.location,
    )
