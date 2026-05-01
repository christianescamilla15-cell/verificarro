"""Tabla `photo_hashes` — perceptual hashes de fotos analizadas.

Cuando un reporte se genera, las fotos del anuncio se procesan con
`imagehash.phash()` (perceptual hash, 64 bits). Se almacena el hash
junto con el `listing_hash` del reporte.

Antes de generar el siguiente reporte, buscamos hashes existentes
con **Hamming distance ≤ 5** (de 64 bits) — si encontramos match
con un `listing_hash` distinto, es bandera fuerte: la misma foto
está siendo usada en dos anuncios distintos.

## Por qué pHash y no CLIP

CLIP da semantic embeddings (caro, ~150MB modelo, requiere GPU
para batch). pHash:

- Pure Python, ~5ms por imagen
- Robusto a resize, JPEG re-compression, ligero color shift
- Detecta duplicates exactos + near-duplicates (la misma foto re-encodeada)
- 64 bits → comparación O(1) con índice + filtro post-fetch

CLIP es mejor para "MISMO auto fotografiado en momentos distintos"
(detección semántica). Para MVP scan-first donde el fraude típico
es "foto stock copiada literal", pHash es suficiente.

## Indexing

`phash` se almacena como `BIGINT` (8 bytes) — orden eficiente para
range queries. Para Hamming distance directa, post-filtramos en
Python después del fetch range.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class PhotoHash(Base, TimestampMixin):
    __tablename__ = "photo_hashes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Match contra ReportRecord.listing_hash — qué reporte generó esta foto
    listing_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Posición en photo_findings (matchea con `PhotoFinding.photo_index`)
    photo_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # 64-bit perceptual hash. Se almacena como int (signed) para
    # ordering / range queries. La conversión a/de imagehash.ImageHash
    # se hace en la capa de servicio.
    phash: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # URL de la foto en el CDN del listing (para auditoría / debug)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # Cuándo capturamos esta foto
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        Index("ix_photo_hashes_phash", "phash"),
        Index("ix_photo_hashes_listing_hash", "listing_hash"),
    )

    def __repr__(self) -> str:
        return (
            f"<PhotoHash listing={self.listing_hash[:8]} "
            f"idx={self.photo_index} phash={self.phash:016x}>"
        )
