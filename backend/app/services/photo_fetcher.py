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

## SSRF protection (MOD-003)

Las URLs vienen del `manual_listing.photo_urls` provisto por el
usuario o de scrapers. Sin protección, un atacante podría meter
`http://169.254.169.254/computeMetadata/v1/instance/service-accounts/`
y leer el token de service account de Render/GCP, o
`http://localhost:5432/` para fingerprint del Postgres interno.

`_check_url_safe` valida ANTES del fetch:
1. Esquema en {http, https} (rechaza file://, gopher://, etc.)
2. Hostname resuelve a IPs públicas (no loopback, privadas,
   link-local, reservadas, multicast)
3. httpx con follow_redirects=False — si hay 3xx, no seguimos
   automáticamente porque el destino del redirect podría ser
   privado aunque el original sea público.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_MAX_BYTES = 4 * 1024 * 1024  # 4 MB
_TIMEOUT_SEC = 8.0
_CONCURRENT = 4
_ALLOWED_SCHEMES = {"http", "https"}


def _check_url_safe(url: str) -> tuple[bool, str]:
    """Valida que la URL apunta a un host público y usa http(s).

    Returns:
        (allowed, reason). Si `allowed=False`, `reason` describe por
        qué para que se loguee. Nunca raises — el caller decide.
    """
    if not url or not isinstance(url, str):
        return False, "url vacía o tipo inválido"

    try:
        parsed = urlparse(url)
    except ValueError as exc:
        return False, f"url malformada: {exc}"

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return False, f"scheme no permitido: {parsed.scheme!r}"

    host = parsed.hostname
    if not host:
        return False, "url sin hostname"

    # Resolver DNS. Si el host ya es IP literal, getaddrinfo la devuelve
    # tal cual; si es nombre, las IPs A + AAAA reales. Bloqueamos si
    # CUALQUIERA es no-pública (atacante podría apuntar un dominio que
    # él controla a 169.254.169.254 — DNS rebinding).
    try:
        addrs = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        return False, f"dns falla: {exc}"

    for family, _, _, _, sockaddr in addrs:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"ip inválida: {ip_str!r}"
        # is_global cubre la mayoría (loopback, private, link-local,
        # reserved, unspecified). Pero algunas multicast routeables
        # (224.0.0.0/4) marcan is_global=True en Python 3.12+, así que
        # las excluimos explícitamente. Para fetch de fotos no
        # esperamos multicast nunca.
        if not ip.is_global or ip.is_multicast:
            return False, f"ip no pública: {ip_str}"

    return True, ""


async def fetch_photos(urls: list[str]) -> list[bytes | None]:
    """Descarga las fotos en paralelo. Devuelve lista del mismo largo
    con `bytes` por foto o `None` si la descarga falló, excedió el
    límite, o la URL no pasó SSRF check. Mantiene el orden para que
    `photo_index` siga válido en los analyzers downstream.
    """
    if not urls:
        return []

    sem = asyncio.Semaphore(_CONCURRENT)

    async def _fetch(url: str) -> bytes | None:
        # SSRF check primero — sin red.
        allowed, reason = _check_url_safe(url)
        if not allowed:
            logger.warning("Foto rechazada por SSRF check (%s): %s", reason, url)
            return None

        async with sem:
            try:
                # follow_redirects=False — si el server público
                # redirecciona a un host privado, no lo seguimos
                # automáticamente. Si el caso de uso real necesita
                # redirects, hay que re-validar la URL del Location.
                async with httpx.AsyncClient(
                    timeout=_TIMEOUT_SEC, follow_redirects=False
                ) as client:
                    response = await client.get(url)
                    if response.is_redirect:
                        logger.info(
                            "Foto redirect no seguido (%s → %s)",
                            url, response.headers.get("location"),
                        )
                        return None
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
