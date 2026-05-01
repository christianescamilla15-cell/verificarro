"""Multi-marketplace cross-listing — busca el mismo auto en otros sitios MX.

Cuando un comprador encuentra un auto en Mercado Libre, vale oro saber
si **el MISMO vendedor lo está anunciando también** en Vivanuncios, OLX,
FB Marketplace, Kavak, etc. Cross-listings pueden indicar:

- **Precio inconsistente** entre sitios (vendedor probando precio
  máximo en uno, mínimo en otro)
- **Mismas fotos en distinto vendedor** (foto stock revendida = estafa)
- **Mismo auto vendido como "particular" Y "concesionario"** (banderazo
  de fraude)

## Estructura

Cada marketplace implementa la interface `MarketplaceSearchProvider`
(método `search`). El despachador `find_cross_listings` los corre en
paralelo y consolida el resultado.

## Estado actual de implementaciones

| Marketplace        | Implementación | Notas |
|--------------------|----------------|-------|
| Vivanuncios        | ✅ HTTP scraping (público sin auth) | |
| Seminuevos.com     | ✅ HTTP scraping (público) | |
| OLX MX             | 🔶 Stub (requiere Apify cuando crezca) | |
| FB Marketplace     | 🔶 Stub (requiere login + Apify) | |
| Kavak              | 🔶 Stub (sitio agresivo anti-bot) | |

Cuando Christian active cuenta Apify, los stubs se reemplazan con
actors reales. Cada marketplace falla limpio si el HTML cambia o el
site cae — `find_cross_listings` siempre devuelve algo, aunque sea
lista vacía.

## Costo

- Vivanuncios + Seminuevos: $0 (HTTP directo, ~3-5s por búsqueda)
- Apify actors (cuando se conecten): ~$0.001 por marketplace × 5 =
  $0.005 USD por reporte completo
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Literal, Protocol

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Identificador del marketplace en findings
MarketplaceId = Literal[
    "vivanuncios", "seminuevos", "olx_mx", "fb_marketplace", "kavak",
]


@dataclass(frozen=True)
class CrossListing:
    """Un auto encontrado en otro marketplace que matchea con la búsqueda."""

    marketplace: MarketplaceId
    title: str
    price_mxn: float | None
    url: str
    location: str = ""
    photos: list[str] = field(default_factory=list)
    seller_name: str = ""
    notes: str = ""


@dataclass
class CrossListingResult:
    """Resultado consolidado para mostrar al usuario."""

    listings: list[CrossListing] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.listings)


class MarketplaceSearchProvider(Protocol):
    """Interface que debe implementar cada scraper de marketplace."""

    name: MarketplaceId

    async def search(
        self, make: str, model: str, year: int | None = None
    ) -> list[CrossListing]:
        """Busca listings activos del make/model/año en este marketplace.

        Devuelve lista vacía si no encuentra o el sitio falla. NO debe
        lanzar excepciones — captúralas internamente y loguea.
        """
        ...


# ---------------------------------------------------------------------------
# Vivanuncios — implementación real
#
# Vivanuncios.com.mx tiene búsqueda pública sin auth. URL pattern:
#   https://www.vivanuncios.com.mx/s-autos:make:model:year
# Resultado en HTML normal con estructura cards.


_VIVA_BASE = "https://www.vivanuncios.com.mx"
_VIVA_TIMEOUT = 8.0
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


class VivanuncionesProvider:
    name: MarketplaceId = "vivanuncios"

    async def search(
        self, make: str, model: str, year: int | None = None
    ) -> list[CrossListing]:
        if not make or not model:
            return []

        # URL de búsqueda. Vivanuncios usa slugs lowercase con guiones.
        slug = f"{_slugify(make)}-{_slugify(model)}"
        if year:
            slug += f"-{year}"
        url = f"{_VIVA_BASE}/s-autos/{slug}/v1c97p1"

        try:
            async with httpx.AsyncClient(
                timeout=_VIVA_TIMEOUT,
                headers={"User-Agent": _USER_AGENT, "Accept-Language": "es-MX"},
            ) as client:
                response = await client.get(url, follow_redirects=True)
                if response.status_code >= 400:
                    return []
                html = response.text
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning("Vivanuncios fetch falló: %s", exc)
            return []

        return _parse_vivanuncios(html, make, model)


def _parse_vivanuncios(html: str, make: str, model: str) -> list[CrossListing]:
    """Extrae cards de listing del HTML de Vivanuncios.

    Vivanuncios marca cada card con `<div class="tileV2">` o similar.
    Como el DOM cambia, intentamos varios selectors.
    """
    soup = BeautifulSoup(html, "lxml")
    results: list[CrossListing] = []

    # Selectors observados (cambia con frecuencia, lista de tries)
    card_selectors = (
        "div.tileV2",
        "div[data-testid='tile']",
        "article.classified-tile",
        "div.classified-list-item",
    )
    cards: list = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            break

    for card in cards[:10]:  # cap a 10 resultados por marketplace
        try:
            title_el = card.select_one(
                "a.title, h2, h3, a[class*='title']"
            )
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue
            # Solo incluir si match con make+model
            t_lower = title.lower()
            if make.lower() not in t_lower or model.lower() not in t_lower:
                continue

            href = title_el.get("href", "") if title_el else ""
            full_url = href if href.startswith("http") else _VIVA_BASE + href

            price_el = card.select_one(
                "span.price, span[class*='price'], [data-testid='price']"
            )
            price_mxn = _parse_price(
                price_el.get_text(" ", strip=True) if price_el else ""
            )

            location_el = card.select_one(
                "span.location, span[class*='location']"
            )
            location = location_el.get_text(strip=True) if location_el else ""

            photo_el = card.select_one("img")
            photos = []
            if photo_el:
                src = photo_el.get("src") or photo_el.get("data-src", "")
                if src and src.startswith("http"):
                    photos = [src]

            results.append(CrossListing(
                marketplace="vivanuncios",
                title=title,
                price_mxn=price_mxn,
                url=full_url,
                location=location,
                photos=photos,
            ))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Card de Vivanuncios skipeada: %s", exc)
            continue

    return results


# ---------------------------------------------------------------------------
# Seminuevos.com — implementación real
#
# Seminuevos es del grupo Reforma, búsqueda pública sin auth.

_SEMINUEVOS_BASE = "https://www.seminuevos.com"


class SeminuevosProvider:
    name: MarketplaceId = "seminuevos"

    async def search(
        self, make: str, model: str, year: int | None = None
    ) -> list[CrossListing]:
        if not make or not model:
            return []
        slug = f"autos-usados-{_slugify(make)}-{_slugify(model)}"
        url = f"{_SEMINUEVOS_BASE}/{slug}"

        try:
            async with httpx.AsyncClient(
                timeout=_VIVA_TIMEOUT,
                headers={"User-Agent": _USER_AGENT, "Accept-Language": "es-MX"},
            ) as client:
                response = await client.get(url, follow_redirects=True)
                if response.status_code >= 400:
                    return []
                html = response.text
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning("Seminuevos fetch falló: %s", exc)
            return []

        return _parse_seminuevos(html, make, model)


def _parse_seminuevos(html: str, make: str, model: str) -> list[CrossListing]:
    soup = BeautifulSoup(html, "lxml")
    results: list[CrossListing] = []

    cards = soup.select(
        "article.vehicle-card, div.vehicle-result, div[class*='card']"
    )
    for card in cards[:10]:
        try:
            title_el = card.select_one("h2, h3, a[class*='title'], .vehicle-title")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue
            t_lower = title.lower()
            if make.lower() not in t_lower or model.lower() not in t_lower:
                continue

            link_el = card.select_one("a[href*='/']")
            href = link_el.get("href", "") if link_el else ""
            full_url = href if href.startswith("http") else _SEMINUEVOS_BASE + href

            price_el = card.select_one(
                ".price, span[class*='price'], [class*='Price']"
            )
            price_mxn = _parse_price(
                price_el.get_text(" ", strip=True) if price_el else ""
            )

            results.append(CrossListing(
                marketplace="seminuevos",
                title=title,
                price_mxn=price_mxn,
                url=full_url,
            ))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Card de Seminuevos skipeada: %s", exc)
            continue

    return results


# ---------------------------------------------------------------------------
# Stubs para cuando Christian conecte Apify
#
# Cada uno respeta la interfaz pero devuelve [] hasta que tengamos
# implementación real. El llamante no rompe.


class OlxMxProvider:
    """OLX MX — requiere Apify (anti-bot agresivo). Stub por ahora."""
    name: MarketplaceId = "olx_mx"

    async def search(
        self, make: str, model: str, year: int | None = None
    ) -> list[CrossListing]:
        # TODO: implementar cuando Christian active Apify actor olx-mx-search
        return []


class FbMarketplaceProvider:
    """FB Marketplace — requiere login + Apify. Stub por ahora."""
    name: MarketplaceId = "fb_marketplace"

    async def search(
        self, make: str, model: str, year: int | None = None
    ) -> list[CrossListing]:
        # TODO: implementar cuando Christian active Apify actor
        # facebook-marketplace-scraper (requiere FB cookies en variable env)
        return []


class KavakProvider:
    """Kavak — sitio con anti-bot agresivo (Cloudflare). Stub."""
    name: MarketplaceId = "kavak"

    async def search(
        self, make: str, model: str, year: int | None = None
    ) -> list[CrossListing]:
        # TODO: implementar via Apify o residential proxy + stealth
        return []


# ---------------------------------------------------------------------------
# Despachador


_DEFAULT_PROVIDERS: list[MarketplaceSearchProvider] = [
    VivanuncionesProvider(),
    SeminuevosProvider(),
    OlxMxProvider(),
    FbMarketplaceProvider(),
    KavakProvider(),
]


async def find_cross_listings(
    make: str,
    model: str,
    year: int | None = None,
    *,
    providers: list[MarketplaceSearchProvider] | None = None,
) -> CrossListingResult:
    """Busca el make/model/year en todos los marketplaces en paralelo.

    Cada provider se ejecuta de forma independiente — si uno falla, los
    demás siguen. Devuelve `CrossListingResult` con la lista consolidada
    + lista de errores (informativa, no bloqueante).
    """
    providers = providers or _DEFAULT_PROVIDERS
    if not make or not model:
        return CrossListingResult()

    async def _safe(provider):
        try:
            return await provider.search(make, model, year)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Provider %s falló: %s", provider.name, exc)
            return []

    results = await asyncio.gather(*(_safe(p) for p in providers))
    listings: list[CrossListing] = []
    for batch in results:
        listings.extend(batch)
    return CrossListingResult(listings=listings)


# ---------------------------------------------------------------------------
# Helpers


_PRICE_RE = re.compile(r"\$?\s*([\d,]+)(?:\.\d+)?")


def _parse_price(text: str) -> float | None:
    if not text:
        return None
    m = _PRICE_RE.search(text.replace(".", ","))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _slugify(s: str) -> str:
    """Convierte 'Honda Civic' → 'honda-civic'."""
    s = s.lower().strip()
    s = re.sub(r"[áä]", "a", s)
    s = re.sub(r"[éë]", "e", s)
    s = re.sub(r"[íï]", "i", s)
    s = re.sub(r"[óö]", "o", s)
    s = re.sub(r"[úü]", "u", s)
    s = re.sub(r"[ñ]", "n", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")
