"""Photo duplicate detection con perceptual hashing (pHash).

Para cada listing nuevo, hasheamos las fotos descargadas y:

1. Buscamos en `photo_hashes` matches por Hamming distance ≤ 5 con
   `listing_hash` distinto.
2. Si hay match → finding "foto reciclada" con severity=high
   (señal fuerte de fraude — la misma foto en dos anuncios distintos).
3. Almacenamos los nuevos hashes en `photo_hashes` para el próximo
   reporte.

## Por qué Hamming ≤ 5

pHash de 64 bits. Hamming distance es la cuenta de bits que difieren.

- 0 = imagen idéntica (mismo binario o re-encoded sin alteraciones)
- 1-3 = imagen casi idéntica (resize, JPEG quality cambio leve)
- 4-5 = imagen muy similar (color shift menor, crop pequeño)
- 6-10 = imagen relacionada (mismo auto, ángulo distinto)
- 11+ = imágenes distintas

Threshold de 5 captura duplicados-reales sin falsos positivos por
"mismo modelo de auto en distinto color".

## Costo

- Hash: ~5ms por imagen (CPU-bound, no GPU)
- Query DB: ~10ms por foto (range scan + post-filter Hamming)
- Storage: ~50 bytes por hash (despreciable)

## Limitación

pHash NO detecta:
- Fotos del mismo auto desde ángulo diferente
- Fotos editadas (Photoshop) con cambios significativos
- Fotos cropped agresivamente

Para esos casos, CLIP semantic embedding sería superior — fuera
de scope esta iteración (requiere pgvector + modelo ~150MB).
"""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.db.models import PhotoHash

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Hamming distance threshold para considerar match
_HAMMING_THRESHOLD = 5


def compute_phash(image_bytes: bytes) -> int | None:
    """Calcula el pHash 64-bit de una imagen. Devuelve int o None si falla.

    `imagehash.phash` devuelve un objeto ImageHash que internamente es
    un array de bits. Lo convertimos a int de 64 bits para storage.
    """
    if not image_bytes:
        return None
    try:
        import imagehash
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        hash_obj = imagehash.phash(img, hash_size=8)  # 8x8 = 64 bits
    except Exception as exc:  # noqa: BLE001
        logger.debug("pHash falló: %s", exc)
        return None

    # ImageHash → int 64-bit
    bit_str = "".join("1" if b else "0" for row in hash_obj.hash for b in row)
    return _to_signed_64(int(bit_str, 2))


def _to_signed_64(value: int) -> int:
    """Convierte un uint64 a int64 (Python int signed compatible con BIGINT SQL)."""
    if value >= 2**63:
        return value - 2**64
    return value


def hamming_distance(a: int, b: int) -> int:
    """Cuenta de bits que difieren entre dos hashes (XOR + popcount)."""
    a_unsigned = a + 2**64 if a < 0 else a
    b_unsigned = b + 2**64 if b < 0 else b
    return bin(a_unsigned ^ b_unsigned).count("1")


async def find_recycled_photos(
    session: "AsyncSession",
    new_hashes: list[int],
    current_listing_hash: str,
) -> list[tuple[int, dict]]:
    """Para cada hash nuevo, busca matches en photo_hashes con
    listing_hash distinto.

    Devuelve lista de tuplas `(photo_index, match_info)` donde
    `photo_index` es la posición en `new_hashes` y `match_info` tiene
    `listing_hash`, `source_url`, `captured_at`, `hamming` del match
    encontrado más cercano.

    Si no hay match para un photo_index, no aparece en el resultado.
    """
    matches: list[tuple[int, dict]] = []

    for idx, new_hash in enumerate(new_hashes):
        if new_hash is None:
            continue

        # Pre-filter: cargamos todos los hashes existentes en una query
        # batched. Para volumen <100k esto es OK; cuando crezca usamos
        # SQL bitcount y range queries.
        result = await session.execute(
            select(PhotoHash).where(
                PhotoHash.listing_hash != current_listing_hash
            )
        )
        candidates = result.scalars().all()

        best_match = None
        best_distance = _HAMMING_THRESHOLD + 1
        for candidate in candidates:
            d = hamming_distance(new_hash, candidate.phash)
            if d < best_distance:
                best_distance = d
                best_match = candidate

        if best_match and best_distance <= _HAMMING_THRESHOLD:
            matches.append((idx, {
                "listing_hash": best_match.listing_hash,
                "source_url": best_match.source_url,
                "captured_at": best_match.captured_at.isoformat()
                if best_match.captured_at else None,
                "hamming": best_distance,
                "previous_photo_index": best_match.photo_index,
            }))

    return matches


async def store_photo_hashes(
    session: "AsyncSession",
    listing_hash: str,
    hashes: list[tuple[int, str | None]],
) -> None:
    """Almacena los nuevos hashes para este listing.

    `hashes`: lista de `(phash_int, source_url)` tuples — una entrada
    por foto. El `photo_index` se infiere del orden.
    """
    now = datetime.now(UTC)
    for idx, (phash, source_url) in enumerate(hashes):
        if phash is None:
            continue
        record = PhotoHash(
            listing_hash=listing_hash,
            photo_index=idx,
            phash=phash,
            source_url=source_url,
            captured_at=now,
        )
        session.add(record)
    # Commit lo hace el caller (mismo session que el resto del pipeline)
