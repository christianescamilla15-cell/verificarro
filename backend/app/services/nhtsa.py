"""NHTSA vPIC API client — VIN decode oficial del fabricante.

NHTSA (National Highway Traffic Safety Administration, USA) mantiene
la base más completa pública de VINs. Su API "vPIC" (Vehicle Product
Information Catalog) decodifica un VIN devolviendo specs originales:
make, model, model year, body class, engine type, transmission,
drive type, GVWR, displacement, fuel type, número de puertas, etc.

Crítico para Verificarro porque:

- **Detecta placa clonada con más confianza**: si el VIN dice
  "Honda Civic 2018 sedán 4-door" y el anuncio dice "Honda CR-V SUV",
  el WMI local puede empatar (Honda → Honda) pero el body class no.
  Esto sube la sensibilidad anti-clonación.
- **Recalls activos**: vPIC también expone recalls del fabricante.
  Un comprador debería saber si el modelo tiene recall vigente.
- **Sin auth, sin rate limit publicado** (uso "razonable" — internamente
  cacheamos 24h por VIN para minimizar requests).
- **Cobertura**: USA es exhaustivo, MX/Asia/Europa cubre los modelos
  exportados a USA (que es la mayoría que circula en MX moderno).

## Endpoint

GET https://vpic.nhtsa.dot.gov/api/vehicles/decodevin/{VIN}?format=json&modelyear={year}

## Degradación

Si el endpoint no responde (timeout, 5xx, network), devolvemos None y
el pipeline sigue con solo el decoder local. El VIN check NO se
bloquea — esto es enrichment, no requirement.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)


_NHTSA_DECODE_URL = (
    "https://vpic.nhtsa.dot.gov/api/vehicles/decodevin/{vin}?format=json"
)
_NHTSA_TIMEOUT_SEC = 8.0  # más tolerante que un scrape, NHTSA suele responder <2s


@dataclass(frozen=True)
class NhtsaDecodeResult:
    """Subset relevante de la respuesta vPIC.

    Todos los campos son opcionales — vPIC los reporta vacíos cuando
    no aplican o no están en su DB. La verdad-de-tierra es que para
    VINs MX nuevos (Mazda Sonora, VW Puebla) los specs vienen
    completos; para VINs de marcas chinas (Chirey, BYD) suele venir
    parcial.
    """

    raw_vin: str
    found: bool = False
    make: str | None = None
    model: str | None = None
    model_year: int | None = None
    body_class: str | None = None  # "Sedan", "SUV", "Pickup", etc.
    vehicle_type: str | None = None
    series: str | None = None
    trim: str | None = None
    engine_cylinders: int | None = None
    engine_displacement_l: float | None = None
    engine_kw: float | None = None
    fuel_type_primary: str | None = None
    transmission_style: str | None = None
    drive_type: str | None = None
    doors: int | None = None
    plant_country: str | None = None
    plant_city: str | None = None
    error_code: str | None = None
    error_text: str | None = None
    raw_fields: dict[str, str] = field(default_factory=dict)


# Mapeo de Variable → atributo. Mantenemos un subset; vPIC retorna
# ~140 campos pero la mayoría son nicho (HEV details, bus specs,
# motorcycle frame, etc.).
_VAR_MAP: dict[str, str] = {
    "Make": "make",
    "Model": "model",
    "Model Year": "model_year",
    "Body Class": "body_class",
    "Vehicle Type": "vehicle_type",
    "Series": "series",
    "Trim": "trim",
    "Engine Number of Cylinders": "engine_cylinders",
    "Displacement (L)": "engine_displacement_l",
    "Engine Power (kW)": "engine_kw",
    "Fuel Type - Primary": "fuel_type_primary",
    "Transmission Style": "transmission_style",
    "Drive Type": "drive_type",
    "Doors": "doors",
    "Plant Country": "plant_country",
    "Plant City": "plant_city",
    "Error Code": "error_code",
    "Error Text": "error_text",
}


async def decode_vin(vin: str) -> NhtsaDecodeResult | None:
    """Decodifica un VIN contra NHTSA vPIC. Devuelve None en error/timeout.

    El llamante decide qué hacer si es None — típicamente el pipeline
    continúa con el decoder local solamente.
    """
    if not vin or len(vin) != 17:
        return None

    url = _NHTSA_DECODE_URL.format(vin=vin.upper())
    try:
        async with httpx.AsyncClient(timeout=_NHTSA_TIMEOUT_SEC) as client:
            response = await client.get(url)
            response.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning("NHTSA vPIC no respondió para %s: %s", vin, exc)
        return None

    try:
        data = response.json()
    except ValueError:
        logger.warning("NHTSA vPIC devolvió JSON inválido para %s", vin)
        return None

    return parse_response(vin, data)


def parse_response(vin: str, data: dict) -> NhtsaDecodeResult:
    """Convierte el JSON crudo de vPIC en `NhtsaDecodeResult`. Pure, testable.

    vPIC devuelve `Results: [{Variable: ..., Value: ..., ValueId: ...}, ...]`.
    Iteramos y mapeamos al dataclass usando `_VAR_MAP`.
    """
    results = data.get("Results") or []
    raw: dict[str, str] = {}
    fields_out: dict[str, object] = {}

    for item in results:
        var = item.get("Variable")
        value = item.get("Value")
        if not var or value in (None, "", "Not Applicable"):
            continue
        raw[var] = str(value)
        if var in _VAR_MAP:
            fields_out[_VAR_MAP[var]] = _coerce(_VAR_MAP[var], value)

    # `found` = al menos make + model + year se decodificaron
    found = bool(
        fields_out.get("make")
        and fields_out.get("model")
        and fields_out.get("model_year")
    )

    return NhtsaDecodeResult(
        raw_vin=vin.upper(),
        found=found,
        raw_fields=raw,
        **{k: v for k, v in fields_out.items() if k in NhtsaDecodeResult.__annotations__},  # type: ignore[arg-type]
    )


def _coerce(field_name: str, value: object) -> object:
    """Convierte el string crudo de vPIC al tipo del dataclass."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if field_name in {"engine_cylinders", "doors", "model_year"}:
        try:
            return int(float(s))
        except (TypeError, ValueError):
            return None
    if field_name in {"engine_displacement_l", "engine_kw"}:
        try:
            return float(s)
        except (TypeError, ValueError):
            return None
    return s
