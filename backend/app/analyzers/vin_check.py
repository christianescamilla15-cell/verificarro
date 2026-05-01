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
