"""Mercado Libre Motors scraper.

Estrategia (D2):

1. **Playwright** abre la URL con un user-agent realista, locale es-MX y
   viewport de escritorio. Espera el `<h1>` del título antes de extraer
   HTML — selector más estable que el precio (que cambia de className).
2. **Parser puro** sobre el HTML usando BeautifulSoup. Tres fuentes en
   orden de confianza:
   a. JSON-LD (`<script type="application/ld+json">` con `@type=Product`).
      Estable y semántico.
   b. Tabla "ficha técnica" (`<tr>` con `<th>`/`<td>` o estructura
      `ui-pdp-specs`). Contiene Año, Kilómetros, Marca, Modelo.
   c. Regex sobre el título y la URL como último recurso.
3. **Fotos**: galería principal, prefiriendo el variant `_2X_` (alta
   resolución) que ML sirve desde `http2.mlstatic.com`.

`scrape()` es la I/O entry; `parse_listing()` es pura para tests con
fixture (sin red).
"""

from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from app.config import get_settings
from app.models.report import ListingData, Source

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)
_VALID_HOSTS = (
    "articulo.mercadolibre.com.mx",
    "carro.mercadolibre.com.mx",
    "auto.mercadolibre.com.mx",
)
_TITLE_SELECTOR = "h1.ui-pdp-title, h1[class*='title']"


def _is_valid_ml_url(url: str) -> bool:
    return any(host in url for host in _VALID_HOSTS)


async def scrape(url: str) -> ListingData:
    """Fetch a Mercado Libre Motors listing and return normalized data."""
    if not _is_valid_ml_url(url):
        raise ValueError(
            "URL no es de Mercado Libre Motors. Hosts válidos: "
            + ", ".join(_VALID_HOSTS)
        )

    settings = get_settings()
    # Import perezoso para que los tests del parser no requieran Playwright
    # instalado en el venv si solo corren contra fixtures.
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=settings.playwright_headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                locale="es-MX",
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=settings.scrape_timeout_ms,
            )
            try:
                await page.wait_for_selector(_TITLE_SELECTOR, timeout=10_000)
            except Exception:
                # El título puede tardar; seguimos con lo que tengamos.
                pass
            html = await page.content()
        finally:
            await browser.close()

    return parse_listing(html, url)


def parse_listing(html: str, url: str) -> ListingData:
    """Pure parser: HTML → ListingData. Testeable con fixtures."""
    soup = BeautifulSoup(html, "lxml")

    json_ld = _extract_json_ld_product(soup)
    specs = _extract_specs(soup)

    title = _extract_title(soup, json_ld)
    price = _extract_price(soup, json_ld)
    description = _extract_description(soup, json_ld)
    photos = _extract_photos(soup, json_ld)
    location = _extract_location(soup)
    seller = _extract_seller(soup)

    year = _coerce_int(specs.get("año") or specs.get("ano"))
    kms = _coerce_int(specs.get("kilómetros") or specs.get("kilometros"))
    make = (specs.get("marca") or "").strip()
    model = (specs.get("modelo") or "").strip()
    trim = (specs.get("versión") or specs.get("version") or "").strip() or None

    if not year:
        year = _year_from_text(title) or _year_from_text(url) or 0
    if not make or not model:
        guessed_make, guessed_model = _make_model_from_title(title)
        make = make or guessed_make
        model = model or guessed_model

    return ListingData(
        source=Source.MERCADOLIBRE,
        source_url=url,
        title=title,
        price_mxn=price,
        year=year,
        make=make,
        model=model,
        trim=trim,
        kilometers=kms or 0,
        location=location,
        description=description,
        seller_name=seller,
        photo_urls=photos,
    )


# ---------------------------------------------------------------------------
# JSON-LD


def _extract_json_ld_product(soup: BeautifulSoup) -> dict[str, Any]:
    """Return the first @type=Product JSON-LD block as a dict, or {}."""
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            type_value = item.get("@type")
            if isinstance(type_value, list):
                if "Product" in type_value:
                    return item
            elif type_value == "Product":
                return item
    return {}


# ---------------------------------------------------------------------------
# Specs (ficha técnica)


def _extract_specs(soup: BeautifulSoup) -> dict[str, str]:
    """Recolecta pares (clave normalizada → valor) de la ficha técnica.

    ML usa varios layouts a lo largo del tiempo; los probamos todos y
    fusionamos. Las claves se normalizan a minúsculas sin acentos para
    facilitar lookup.
    """
    specs: dict[str, str] = {}

    # Layout antiguo: <tr><th>Año</th><td>2018</td></tr>
    for row in soup.select("table.andes-table tr, .ui-pdp-specs__table tr"):
        head = row.find(["th", "td"])
        cells = row.find_all(["th", "td"])
        if not head or len(cells) < 2:
            continue
        key = _norm_key(cells[0].get_text(strip=True))
        val = cells[1].get_text(" ", strip=True)
        if key and val:
            specs[key] = val

    # Layout "highlighted specs" (chips arriba de la página)
    for spec in soup.select(
        ".ui-vpp-highlighted-specs__attribute, .ui-pdp-specs__attribute"
    ):
        label = spec.select_one(
            ".ui-vpp-highlighted-specs__attribute-label, "
            ".ui-pdp-specs__attribute-label"
        )
        value = spec.select_one(
            ".ui-vpp-highlighted-specs__attribute-value, "
            ".ui-pdp-specs__attribute-value"
        )
        if label and value:
            key = _norm_key(label.get_text(strip=True))
            val = value.get_text(" ", strip=True)
            if key and val:
                specs[key] = val

    # Striped key-value list
    for li in soup.select(".ui-pdp-list__item"):
        text = li.get_text(":", strip=True)
        if ":" in text:
            k, _, v = text.partition(":")
            key = _norm_key(k)
            val = v.strip()
            if key and val:
                specs.setdefault(key, val)

    return specs


def _norm_key(s: str) -> str:
    table = str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN")
    return s.translate(table).strip().lower()


# ---------------------------------------------------------------------------
# Field extractors


def _extract_title(soup: BeautifulSoup, json_ld: dict[str, Any]) -> str:
    name = json_ld.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    h1 = soup.select_one(_TITLE_SELECTOR)
    if h1:
        return h1.get_text(strip=True)
    return ""


def _extract_price(soup: BeautifulSoup, json_ld: dict[str, Any]) -> float:
    offers = json_ld.get("offers") or {}
    if isinstance(offers, list) and offers:
        offers = offers[0]
    if isinstance(offers, dict):
        raw = offers.get("price")
        try:
            if raw is not None:
                return float(raw)
        except (TypeError, ValueError):
            pass

    # CSS fallback: ML pinta el precio en .andes-money-amount__fraction (entero)
    # y .andes-money-amount__cents (centavos), con separador de miles que hay
    # que limpiar. El selector aria-label suele tener el precio formateado.
    for sel in (
        "[itemprop='price']",
        ".ui-pdp-price__second-line .andes-money-amount__fraction",
        ".andes-money-amount__fraction",
    ):
        el = soup.select_one(sel)
        if not el:
            continue
        raw = el.get("content") or el.get_text(strip=True)
        try:
            return float(raw.replace(",", "").replace(".", "").replace("$", ""))
        except (TypeError, ValueError):
            continue
    return 0.0


def _extract_description(soup: BeautifulSoup, json_ld: dict[str, Any]) -> str:
    desc = json_ld.get("description")
    if isinstance(desc, str) and desc.strip():
        return desc.strip()
    for sel in (
        ".ui-pdp-description__content",
        "[data-testid='description']",
        ".ui-pdp-description",
    ):
        el = soup.select_one(sel)
        if el:
            return el.get_text("\n", strip=True)
    return ""


_PHOTO_BLOCKLIST_PATTERNS = (
    "/catalog-technical-specs/",  # íconos vectoriales de specs
    "/assets/vectorial/",
    "/storage/ui-",  # ícons del header / chrome de ML
    "/storage/seller-icons/",
)


def _is_listing_photo(url: str) -> bool:
    if not url:
        return False
    if url.lower().endswith(".svg"):
        return False
    return not any(blocked in url for blocked in _PHOTO_BLOCKLIST_PATTERNS)


def _extract_photos(soup: BeautifulSoup, json_ld: dict[str, Any]) -> list[str]:
    """Devuelve URLs únicas de fotos del auto, prefiriendo alta resolución."""
    urls: list[str] = []
    seen: set[str] = set()

    def _push(raw: str | None) -> None:
        if not raw:
            return
        upgraded = _upgrade_to_hd(raw)
        if upgraded in seen or not _is_listing_photo(upgraded):
            return
        seen.add(upgraded)
        urls.append(upgraded)

    images_field = json_ld.get("image")
    if isinstance(images_field, str):
        images_field = [images_field]
    if isinstance(images_field, list):
        for u in images_field:
            if isinstance(u, str):
                _push(u)

    for img in soup.select(
        ".ui-pdp-gallery__figure img, "
        ".ui-pdp-image, "
        "figure[class*='gallery'] img"
    ):
        _push(img.get("data-zoom") or img.get("src") or img.get("data-src"))

    return urls


def _upgrade_to_hd(url: str) -> str:
    """ML sirve `D_NQ_NP_2X_..` para HD. Idempotente — no duplica `_2X_`.

    ML mezcla varios prefijos para la misma imagen:
      - `D_NQ_NP_NUMBERS`     (SD)
      - `D_NQ_NP_2X_NUMBERS`  (HD canónica)
      - `D_Q_NP_NUMBERS`      (thumbnail SD)
      - `D_Q_NP_2X_NUMBERS`   (thumbnail HD)
    Normalizamos cualquiera al canónico HD. La sustitución se hace por
    longitud descendente para que `_2X_` no se duplique.
    """
    if "/D_NQ_NP_2X_" in url:
        return url
    for prefix in ("/D_Q_NP_2X_", "/D_NQ_NP_", "/D_Q_NP_"):
        if prefix in url:
            return url.replace(prefix, "/D_NQ_NP_2X_", 1)
    return url


def _extract_location(soup: BeautifulSoup) -> str:
    for sel in (
        ".ui-vip-location__subtitle",
        ".ui-pdp-seller__location",
        "[data-testid='location']",
        ".ui-pdp-media__body",
    ):
        el = soup.select_one(sel)
        if el:
            text = el.get_text(" ", strip=True)
            if text:
                return text
    return ""


def _extract_seller(soup: BeautifulSoup) -> str:
    for sel in (
        ".ui-pdp-seller__header__title",
        ".ui-box-component-pdp__visible--desktop .ui-pdp-seller__link-trigger",
        "[data-testid='seller-name']",
    ):
        el = soup.select_one(sel)
        if el:
            return el.get_text(strip=True)
    return ""


# ---------------------------------------------------------------------------
# Coercion / regex helpers


def _coerce_int(s: str | None) -> int:
    if not s:
        return 0
    digits = re.sub(r"[^0-9]", "", s)
    return int(digits) if digits else 0


def _year_from_text(text: str) -> int:
    if not text:
        return 0
    m = re.search(r"(19[7-9]\d|20[0-3]\d)", text)
    return int(m.group(1)) if m else 0


_KNOWN_MAKES = {
    "acura", "alfa", "audi", "bmw", "buick", "cadillac", "chevrolet",
    "chrysler", "dodge", "fiat", "ford", "gmc", "honda", "hyundai",
    "infiniti", "jaguar", "jeep", "kia", "land", "lexus", "lincoln",
    "mazda", "mercedes", "mercedes-benz", "mini", "mitsubishi", "nissan",
    "peugeot", "porsche", "ram", "renault", "saab", "seat", "subaru",
    "suzuki", "tesla", "toyota", "volkswagen", "vw", "volvo", "byd",
    "changan", "chirey", "chery", "geely", "jac", "jetour", "mg", "omoda",
    "rover",
}


def _make_model_from_title(title: str) -> tuple[str, str]:
    """Extrae (marca, modelo) heurísticamente del título.

    Devuelve `("", "")` si no encuentra una marca conocida.
    """
    if not title:
        return "", ""
    tokens = re.split(r"\s+", title.strip())
    lowered = [t.lower() for t in tokens]
    for i, tok in enumerate(lowered):
        if tok in _KNOWN_MAKES:
            make = tokens[i].title()
            model = tokens[i + 1].title() if i + 1 < len(tokens) else ""
            return make, model
    return "", ""
