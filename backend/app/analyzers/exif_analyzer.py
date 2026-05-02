"""Análisis de metadata EXIF en fotos del anuncio.

Lo que detectamos sin llamar a la red ni Claude:

| Señal                                                    | Severidad | Por qué importa |
|----------------------------------------------------------|-----------|-----------------|
| Software field menciona Photoshop/GIMP/Lightroom/AI tool | medium    | Foto editada — pintura, óxido o golpe pueden estar oculto |
| Multiples fotos con el MISMO `DateTimeOriginal`          | medium    | Batch fake o foto duplicada por el sistema del vendedor |
| `DateTimeOriginal` muy viejo (>3 años) vs listing nuevo  | low       | Foto reciclada de venta anterior o auto que llevan años intentando vender |
| Sin metadata EXIF en TODAS las fotos                     | low       | CDN strip (esperado en ML/FB), pero info para el reporte |

## Lo que NO detectamos aquí (out of scope esta iteración)

- GPS coordinates vs listing.location (necesita geocoding del listing
  text, complicado y propenso a falsos positivos)
- Manipulación al pixel (Error Level Analysis, AI tampering detection)
  — eso vive en CLIP / Replicate / un modelo dedicado
- Reverse image search — vive en TinEye/Google Lens

## Costo

$0. Pure Python sobre Pillow. <50ms por foto típica.

## Mercado Libre / Facebook reality check

Ambos CDNs strip metadata EXIF al subir/reescalar la foto. En la
práctica, las fotos de listings ML vendrán SIN EXIF la mayoría del
tiempo. Por eso la "no_exif" es solo `low` y no se pone en el
score crítico — es info contextual.

El valor real de EXIF se desbloquea cuando el usuario sube fotos
directamente (flow PRO de Facebook Marketplace o futura subida
manual). Ahí sí salen Software=Photoshop o batch-same-timestamp.
"""

from __future__ import annotations

import io
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

logger = logging.getLogger(__name__)


# Software fields que indican edición. Lista no exhaustiva pero cubre
# las herramientas comunes — match es case-insensitive substring.
_EDIT_SOFTWARE_KEYWORDS = (
    "photoshop", "lightroom", "gimp", "affinity", "pixelmator",
    "snapseed", "vsco", "facetune", "remini",
    # AI tools (cada vez más comunes para "limpiar" defectos)
    "midjourney", "stable diffusion", "dall-e", "dalle",
    "topaz", "photomator",
)

# Antigüedad de la foto que dispara aviso (años)
_OLD_PHOTO_YEARS = 3


# Severidad type alias compatible con `PhotoFinding.severity`
Severity = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class ExifMetadata:
    """Subset relevante de la EXIF de una imagen."""

    has_exif: bool
    datetime_original: datetime | None = None
    software: str | None = None
    make: str | None = None
    model: str | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None


# MOD-016: ExifFinding ahora es directamente el Pydantic v2 model que
# el Report consume. El dataclass espejo se eliminó — antes
# ExifFinding (dataclass) y ExifFindingModel (Pydantic) eran espejos
# byte-por-byte y un mapper en pipeline.steps.resolve_exif los
# convertía. Ese mapper ya no es necesario; el analyzer regresa
# directamente Pydantic y el Report lo consume sin conversión.
from app.models.report import ExifFindingModel as ExifFinding


def extract_metadata(image_bytes: bytes | None) -> ExifMetadata:
    """Lee la EXIF de un blob de imagen. Pure, no red.

    Retorna `ExifMetadata(has_exif=False, ...)` si:
    - bytes es None (descarga falló)
    - Pillow no puede abrir la imagen
    - La imagen no tiene EXIF tag
    """
    if not image_bytes:
        return ExifMetadata(has_exif=False)

    try:
        from PIL import ExifTags, Image

        img = Image.open(io.BytesIO(image_bytes))
        exif = img.getexif()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Pillow no pudo abrir imagen: %s", exc)
        return ExifMetadata(has_exif=False)

    if not exif:
        return ExifMetadata(has_exif=False)

    # Mapea tag IDs (números) a nombres legibles
    tag_map = {ExifTags.TAGS.get(tag_id, tag_id): val for tag_id, val in exif.items()}

    return ExifMetadata(
        has_exif=True,
        datetime_original=_parse_exif_datetime(
            tag_map.get("DateTimeOriginal") or tag_map.get("DateTime")
        ),
        software=_clean_string(tag_map.get("Software")),
        make=_clean_string(tag_map.get("Make")),
        model=_clean_string(tag_map.get("Model")),
        gps_lat=_extract_gps(exif, lat_or_lon="lat"),
        gps_lon=_extract_gps(exif, lat_or_lon="lon"),
    )


def analyze_batch(
    metadatas: list[ExifMetadata], *, listing_year: int | None = None
) -> list[ExifFinding]:
    """Aplica las heurísticas cross-foto sobre la lista ordenada de EXIF.

    El orden de `metadatas` debe coincidir con el orden de las fotos
    en el reporte (mismo `photo_index`).

    `listing_year` se usa para detectar fotos viejas — si no se provee,
    se usa el año actual.
    """
    findings: list[ExifFinding] = []
    if not metadatas:
        return findings

    cutoff_year = (
        listing_year if listing_year and listing_year > 1990
        else datetime.now(UTC).year
    )
    cutoff_date = datetime(cutoff_year - _OLD_PHOTO_YEARS, 1, 1)

    # 1) Software de edición por foto
    for idx, meta in enumerate(metadatas):
        if meta.has_exif and meta.software:
            sw_lower = meta.software.lower()
            for kw in _EDIT_SOFTWARE_KEYWORDS:
                if kw in sw_lower:
                    findings.append(ExifFinding(
                        photo_index=idx,
                        flag="edited_software",
                        severity="medium",
                        note=(
                            f"Foto editada con '{meta.software}'. "
                            "Pintura, óxido o golpes pueden estar retocados."
                        ),
                    ))
                    break

    # 2) Foto vieja vs listing nuevo
    for idx, meta in enumerate(metadatas):
        if meta.datetime_original and meta.datetime_original < cutoff_date:
            findings.append(ExifFinding(
                photo_index=idx,
                flag="old_photo",
                severity="low",
                note=(
                    f"Foto tomada el "
                    f"{meta.datetime_original.strftime('%Y-%m-%d')}, "
                    f"hace más de {_OLD_PHOTO_YEARS} años. Posible foto "
                    "reciclada o auto que llevan tiempo intentando vender."
                ),
            ))

    # 3) Mismo timestamp en >2 fotos — batch fake / dump
    timestamps = [m.datetime_original for m in metadatas if m.datetime_original]
    if timestamps:
        counts = Counter(timestamps)
        for ts, count in counts.items():
            if count > 2:
                # Marca la PRIMERA foto con ese timestamp duplicado
                first_idx = next(
                    i for i, m in enumerate(metadatas)
                    if m.datetime_original == ts
                )
                findings.append(ExifFinding(
                    photo_index=first_idx,
                    flag="duplicate_timestamp",
                    severity="medium",
                    note=(
                        f"{count} fotos comparten timestamp "
                        f"{ts.strftime('%Y-%m-%d %H:%M')}. Sospechoso: "
                        "podría ser dump batch o foto duplicada."
                    ),
                ))

    # 4) Si TODAS las fotos no tienen EXIF: info-tag (esperado en ML CDN
    #    pero relevante para flujos de upload directo)
    if metadatas and all(not m.has_exif for m in metadatas):
        findings.append(ExifFinding(
            photo_index=0,
            flag="no_exif_anywhere",
            severity="low",
            note=(
                "Ninguna foto tiene metadata EXIF. Normal en ML/FB (sus CDN "
                "la quitan), pero si el vendedor te las envía directo y "
                "siguen sin EXIF, las fotos podrían no ser propias."
            ),
        ))

    return findings


# ---------------------------------------------------------------------------
# Helpers


def _parse_exif_datetime(raw: object) -> datetime | None:
    """EXIF datetime es 'YYYY:MM:DD HH:MM:SS'."""
    if not raw:
        return None
    s = str(raw).strip()
    try:
        return datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _clean_string(raw: object) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().strip("\x00")
    return s or None


def _extract_gps(exif, *, lat_or_lon: Literal["lat", "lon"]) -> float | None:
    """GPS info viene en sub-IFD. Pillow lo expone vía `get_ifd`.

    Devuelve coordenada decimal con signo (negativo si Sur/Oeste).
    Si la imagen no tiene GPS, devuelve None.
    """
    try:
        from PIL.ExifTags import IFD, GPSTAGS

        gps_ifd = exif.get_ifd(IFD.GPSInfo)
    except Exception:  # noqa: BLE001
        return None
    if not gps_ifd:
        return None

    tag_map = {GPSTAGS.get(tid, tid): val for tid, val in gps_ifd.items()}

    if lat_or_lon == "lat":
        coord = tag_map.get("GPSLatitude")
        ref = tag_map.get("GPSLatitudeRef", "N")
        sign = -1 if str(ref).upper().startswith("S") else 1
    else:
        coord = tag_map.get("GPSLongitude")
        ref = tag_map.get("GPSLongitudeRef", "E")
        sign = -1 if str(ref).upper().startswith("W") else 1

    if not coord or len(coord) != 3:
        return None
    try:
        deg, min_, sec = (float(c) for c in coord)
    except (TypeError, ValueError):
        return None
    decimal = deg + min_ / 60 + sec / 3600
    return sign * decimal
