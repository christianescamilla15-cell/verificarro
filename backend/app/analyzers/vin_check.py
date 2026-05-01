"""Comparador del VIN escaneado contra los datos del anuncio.

Función pura: VIN string + ListingData + RepuveResult opcional → resultado
con `matches` boolean y `alerts` lista. Sin red, sin API.

## Reglas de comparación

| Comparación                              | Tolerancia    | Severidad si falla |
|------------------------------------------|---------------|--------------------|
| Marca decoded vs `listing.make`          | aliases OK    | high               |
| Año decoded vs `listing.year`            | ±1 año        | medium             |
| VIN escaneado vs VIN en descripción      | exacto        | high               |
| VIN escaneado vs `repuve_manual.vin`     | exacto        | high               |
| Checksum ISO 3779 inválido               | -             | medium (info)      |
| Formato VIN inválido                     | -             | high               |

## Extracción de VIN de la descripción

Si el vendedor pegó un VIN en `listing.description`, lo extraemos con
regex `[A-HJ-NPR-Z0-9]{17}` y lo comparamos contra el VIN escaneado.
Si difieren → alerta inmediata: el vendedor te dio un VIN distinto
al del auto físico.

Esta extracción siempre se ejecuta, incluso si el usuario no escanea
nada — la guardamos en `vin_in_description` para mostrarse en el
reporte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from app.analyzers.vin_decoder import VinDecoded, decode, normalize_vin
from app.models.report import ListingData, RepuveResult
from app.services.nhtsa import NhtsaDecodeResult, decode_vin as nhtsa_decode


# Coincide con cualquier substring de 17 caracteres alfanuméricos válidos
# (sin I/O/Q). El word-boundary evita cazar 17 chars dentro de palabras
# más largas.
_VIN_IN_TEXT_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")


@dataclass(frozen=True)
class VinAlert:
    severity: Literal["low", "medium", "high"]
    message: str


@dataclass(frozen=True)
class VinCheckResult:
    decoded: VinDecoded
    matches_listing: bool
    alerts: list[VinAlert] = field(default_factory=list)
    vin_in_description: str | None = None
    nhtsa: NhtsaDecodeResult | None = None
    scanned_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def check(
    raw_vin: str,
    listing: ListingData,
    repuve: RepuveResult | None = None,
) -> VinCheckResult:
    """Decodifica el VIN escaneado y lo compara contra el anuncio."""
    decoded = decode(raw_vin)
    alerts: list[VinAlert] = []

    if not decoded.valid_format:
        alerts.append(VinAlert(
            severity="high",
            message="VIN inválido — verifica que escaneaste los 17 caracteres correctos",
        ))
        return VinCheckResult(
            decoded=decoded, matches_listing=False, alerts=alerts,
            vin_in_description=_extract_vin_from_text(listing.description),
        )

    # Extracción del VIN de la descripción del anuncio (siempre)
    vin_in_desc = _extract_vin_from_text(listing.description)

    # Marca
    matches_make = _check_make(decoded, listing, alerts)

    # Año
    matches_year = _check_year(decoded, listing, alerts)

    # VIN en descripción vs escaneado
    if vin_in_desc and vin_in_desc != decoded.vin:
        alerts.append(VinAlert(
            severity="high",
            message=(
                f"El anuncio menciona el VIN '{vin_in_desc}' pero el auto "
                f"físico tiene '{decoded.vin}'. NO COINCIDEN."
            ),
        ))

    # VIN del REPUVE manual vs escaneado
    if repuve and repuve.vin and normalize_vin(repuve.vin) != decoded.vin:
        alerts.append(VinAlert(
            severity="high",
            message=(
                f"El VIN consultado en REPUVE ('{repuve.vin}') no coincide "
                f"con el del auto físico ('{decoded.vin}'). Posible "
                "clonación de placa."
            ),
        ))

    # Checksum: solo informativo, no decide matches_listing
    if not decoded.valid_checksum:
        alerts.append(VinAlert(
            severity="medium",
            message=(
                "Checksum ISO 3779 inválido. El VIN puede estar mal "
                "escrito o ser inválido. (Algunos VINs europeos legítimos "
                "fallan este check)."
            ),
        ))

    matches = matches_make and matches_year and not any(
        a.severity == "high" for a in alerts
    )

    return VinCheckResult(
        decoded=decoded,
        matches_listing=matches,
        alerts=alerts,
        vin_in_description=vin_in_desc,
    )


# ---------------------------------------------------------------------------
# Helpers


def _check_make(
    decoded: VinDecoded, listing: ListingData, alerts: list[VinAlert]
) -> bool:
    """Compara `decoded.manufacturer` contra `listing.make` con aliases."""
    if not decoded.manufacturer:
        # WMI desconocido — no podemos validar, pero no es alarma.
        return True
    if not listing.make:
        return True

    decoded_names = {
        decoded.manufacturer.lower(),
        *[a.lower() for a in decoded.manufacturer_aliases],
    }
    listing_make = listing.make.strip().lower()

    if listing_make in decoded_names:
        return True

    alerts.append(VinAlert(
        severity="high",
        message=(
            f"El VIN físico es '{decoded.manufacturer}' pero el anuncio "
            f"dice '{listing.make}'. POSIBLE PLACA CLONADA — no compres."
        ),
    ))
    return False


def _check_year(
    decoded: VinDecoded, listing: ListingData, alerts: list[VinAlert]
) -> bool:
    """Compara año con tolerancia ±1 (modelo año vs año fabricación)."""
    if not decoded.year or not listing.year:
        return True

    diff = abs(decoded.year - listing.year)
    if diff == 0:
        return True
    if diff == 1:
        alerts.append(VinAlert(
            severity="low",
            message=(
                f"El VIN indica año {decoded.year} y el anuncio dice "
                f"{listing.year}. Diferencia de 1 año es normal por "
                "fechas de fabricación vs modelo."
            ),
        ))
        return True

    alerts.append(VinAlert(
        severity="medium" if diff <= 3 else "high",
        message=(
            f"El VIN indica año {decoded.year} pero el anuncio dice "
            f"{listing.year} (diferencia {diff} años). Pregunta al "
            "vendedor o no compres."
        ),
    ))
    return False


def _extract_vin_from_text(text: str | None) -> str | None:
    """Busca un substring de 17 chars VIN-válidos en `text`."""
    if not text:
        return None
    match = _VIN_IN_TEXT_RE.search(text.upper())
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# NHTSA enrichment


# Body class del listing.title contra body class del VIN.
# Si el title menciona alguna de las KEYWORDS de un grupo y NHTSA dice
# que el VIN es de otro grupo distinto, es señal fuerte de placa clonada.
_BODY_CLASS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Sedan/Saloon": ("sedan", "sedán", "saloon"),
    "SUV": ("suv", "crossover", "todo terreno"),
    "Pickup": ("pickup", "pick-up", "pick up", "camioneta de batea"),
    "Hatchback": ("hatchback", "hatch", "5 puertas"),
    "Coupe": ("coupé", "coupe", "deportivo 2 puertas"),
    "Convertible/Cabriolet": ("convertible", "cabrio", "convertable"),
    "Van": ("van", "minivan", "vagoneta"),
}


def _normalize_nhtsa_body(s: str | None) -> str | None:
    """vPIC body_class viene como 'Sedan/Saloon', 'Sport Utility Vehicle (SUV)', etc.
    Lo mapeamos a una bucket nuestra para comparar con keywords del title.
    """
    if not s:
        return None
    s_lower = s.lower()
    if "sedan" in s_lower or "saloon" in s_lower:
        return "Sedan/Saloon"
    if "suv" in s_lower or "sport utility" in s_lower or "crossover" in s_lower:
        return "SUV"
    if "pickup" in s_lower or "truck" in s_lower:
        return "Pickup"
    if "hatchback" in s_lower:
        return "Hatchback"
    if "coupe" in s_lower or "coupé" in s_lower:
        return "Coupe"
    if "convertible" in s_lower or "cabriolet" in s_lower:
        return "Convertible/Cabriolet"
    if "van" in s_lower or "minivan" in s_lower:
        return "Van"
    return None


def _check_body_class_mismatch(
    nhtsa: NhtsaDecodeResult, listing: ListingData, alerts: list[VinAlert]
) -> None:
    """Si el VIN dice un body class y el title del anuncio menciona otro distinto,
    emitimos high alert (clonación-de-placa probable: el auto físico es de
    otra clase corporal que el del listing)."""
    nhtsa_bucket = _normalize_nhtsa_body(nhtsa.body_class)
    if not nhtsa_bucket:
        return

    title = (listing.title or "").lower()
    if not title:
        return

    # ¿El title menciona keywords de OTRA bucket distinta a nhtsa_bucket?
    for bucket, keywords in _BODY_CLASS_KEYWORDS.items():
        if bucket == nhtsa_bucket:
            continue
        if any(kw in title for kw in keywords):
            # El title dice "SUV" pero NHTSA dice "Sedan" → alert
            alerts.append(VinAlert(
                severity="high",
                message=(
                    f"NHTSA reporta que el VIN físico es '{nhtsa.body_class}' "
                    f"pero el anuncio describe un '{bucket}'. POSIBLE PLACA "
                    "CLONADA — el auto físico es de otra carrocería que el "
                    "del anuncio."
                ),
            ))
            return


def _check_make_mismatch_nhtsa(
    nhtsa: NhtsaDecodeResult, listing: ListingData, alerts: list[VinAlert]
) -> None:
    """NHTSA es más autoritativo que el WMI local para make. Si NHTSA
    devolvió make y difiere del listing, emitimos alerta high. (El check
    de make local ya emite high si WMI mismatch — esto cubre el caso donde
    el WMI local no tenía la marca pero NHTSA sí.)"""
    if not nhtsa.make or not listing.make:
        return
    if nhtsa.make.strip().lower() == listing.make.strip().lower():
        return
    # Tolera aliases comunes: NHTSA usa "MERCEDES-BENZ", listings "Mercedes Benz"
    n = nhtsa.make.strip().lower().replace("-", " ")
    l = listing.make.strip().lower().replace("-", " ")
    if n == l:
        return
    alerts.append(VinAlert(
        severity="high",
        message=(
            f"NHTSA reporta que el VIN físico es '{nhtsa.make}' pero el "
            f"anuncio dice '{listing.make}'. Discrepancia oficial — "
            "verifica que el auto sea el mismo del anuncio."
        ),
    ))


async def check_with_enrichment(
    raw_vin: str,
    listing: ListingData,
    repuve: RepuveResult | None = None,
) -> VinCheckResult:
    """Versión async de `check()` que además consulta NHTSA vPIC.

    Flow:
      1. Decode local (sync, instantáneo)
      2. Si VIN inválido → return early con resultado del check sync
      3. NHTSA decode en paralelo (async, ~1-2s)
      4. Merge: agregar campos NHTSA al resultado + alertas adicionales
         (body-class mismatch, make mismatch confirmado por NHTSA)

    Si NHTSA falla (timeout/network), seguimos con el resultado sync —
    NHTSA es enrichment, no requirement.
    """
    base = check(raw_vin, listing, repuve)
    if not base.decoded.valid_format:
        return base

    nhtsa = await nhtsa_decode(base.decoded.vin)
    if nhtsa is None or not nhtsa.found:
        return base

    extra_alerts: list[VinAlert] = list(base.alerts)
    _check_make_mismatch_nhtsa(nhtsa, listing, extra_alerts)
    _check_body_class_mismatch(nhtsa, listing, extra_alerts)

    matches = base.matches_listing and not any(
        a.severity == "high" for a in extra_alerts if a not in base.alerts
    )

    return VinCheckResult(
        decoded=base.decoded,
        matches_listing=matches,
        alerts=extra_alerts,
        vin_in_description=base.vin_in_description,
        nhtsa=nhtsa,
        scanned_at=base.scanned_at,
    )
