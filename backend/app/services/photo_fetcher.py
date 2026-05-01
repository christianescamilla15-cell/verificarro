"""Descarga bytes de las fotos del anuncio para análisis EXIF/forensics.

A diferencia de `photo_analyzer` que pasa la URL directamente a Claude
(Anthropic la jala), aquí necesitamos los bytes en memoria para:

- Leer metadata EXIF con Pillow
- En el futuro: error level analysis, perceptual hashing, CLIP
  embeddings para detectar fotos recicladas

## Límites

- 4 MB por foto (cualquier foto de auto en ML Motors está bajo 2 MB
  típico). Si excede, salta la foto y loguea — better skip than OOM.
- 8s timeout por descarga.
- 4 descargas simultáneas (ML CDN tolera bien, no spamamos).
"""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

_MAX_BYTES = 4 * 1024 * 1024  # 4 MB
_TIMEOUT_SEC = 8.0
_CONCURRENT = 4


async def fetch_photos(urls: list[str]) -> list[bytes | None]:
    """Descarga las fotos en paralelo. Devuelve lista del mismo largo
    con `bytes` por foto o `None` si la descarga falló o excedió el
    límite. Mantiene el orden para que `photo_index` siga válido en
    los analyzers downstream.
    """
    if not urls:
        return []

    sem = asyncio.Semaphore(_CONCURRENT)

    async def _fetch(url: str) -> bytes | None:
        async with sem:
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
                    response = await client.get(url)
                    response.raise_for_status()
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                logger.warning("Foto fetch falló (%s): %s", url, exc)
                return None
            content = response.content
            if len(content) > _MAX_BYTES:
                logger.info(
                    "Foto excede %d bytes (%d), omitida: %s",
                    _MAX_BYTES, len(content), url,
                )
                return None
            return content

    return await asyncio.gather(*(_fetch(u) for u in urls))
