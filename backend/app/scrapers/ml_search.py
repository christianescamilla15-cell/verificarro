"""Mercado Libre Motors search scraper para encontrar comparables.

Dado un (make, model), abre la página de búsqueda en
``https://autos.mercadolibre.com.mx/{slug}`` y extrae los primeros N
items con price, year, kms, location y URL del anuncio.

Como en `mercadolibre.py`, separamos:

- `find_comparables()` → I/O con Playwright (entry async)
- `parse_search_html()` → función pura sobre el HTML para tests con
  fixtures
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from app.config import get_settings

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

# Selectors observed 2026-04-30 en autos.mercadolibre.com.mx.
_CARD_SELECTOR = ".poly-card"
_PRICE_SELECTOR = ".andes-money-amount__fraction"


@dataclass(slots=True)
class Comparable:
    title: str
    price_mxn: float
    year: int
    kilometers: int
    location: str
    url: str


def _slug(make: str, model: str) -> str:
    parts = [p.strip().lower() for p in (make, model) if p and p.strip()]
    slug = "-".join(parts)
    return re.sub(r"[^a-z0-9-]+", "-", slug).strip("-")


def search_url(make: str, model: str) -> str:
    return f"https://autos.mercadolibre.com.mx/{_slug(make, model)}"


async def find_comparables(
    make: str, model: str, *, limit: int = 50
) -> list[Comparable]:
    """Abre la búsqueda y devuelve hasta `limit` comparables.

    No filtra por año/kms — esa lógica vive en `price_estimator`. Aquí
    solo recolectamos crudo.
    """
    if not make or not model:
        return []

    url = search_url(make, model)
    settings = get_settings()
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
                await page.wait_for_selector(_CARD_SELECTOR, timeout=10_000)
            except Exception:
                return []
            html = await page.content()
        finally:
            await browser.close()

    return parse_search_html(html, limit=limit)


def parse_search_html(html: str, *, limit: int = 50) -> list[Comparable]:
    """HTML de la página de search → lista de comparables. Función pura."""
    soup = BeautifulSoup(html, "lxml")
    comparables: list[Comparable] = []
    seen_urls: set[str] = set()

    for card in soup.select(_CARD_SELECTOR):
        if len(comparables) >= limit:
            break
        try:
            comp = _parse_card(card)
        except Exception:
            continue
        if not comp or comp.url in seen_urls:
            continue
        seen_urls.add(comp.url)
        comparables.append(comp)

    return comparables


def _parse_card(card) -> Comparable | None:
    text = card.get_text("\n", strip=True)
    if not text:
        return None
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    price_el = card.select_one(_PRICE_SELECTOR)
    price = _coerce_money(price_el.get_text(strip=True)) if price_el else 0.0

    year = _find_year(lines)
    kms = _find_kms(lines)
    title = _find_title(lines)
    location = _find_location(lines)

    link_el = card.select_one("a[href*='MLM']")
    url = (link_el.get("href") if link_el else "") or ""
    url = url.split("#")[0] if url else ""

    if price <= 0 or year < 1990 or not url:
        return None

    return Comparable(
        title=title,
        price_mxn=price,
        year=year,
        kilometers=kms,
        location=location,
        url=url,
    )


_YEAR_RE = re.compile(r"^(19[7-9]\d|20[0-3]\d)$")
_KMS_RE = re.compile(r"^([\d.,]+)\s*km$", re.IGNORECASE)
_LOCATION_RE = re.compile(r"-\s*[A-ZÁÉÍÓÚ]")


def _find_year(lines: list[str]) -> int:
    for line in lines:
        m = _YEAR_RE.match(line)
        if m:
            return int(m.group(1))
    return 0


def _find_kms(lines: list[str]) -> int:
    for line in lines:
        m = _KMS_RE.match(line)
        if m:
            digits = re.sub(r"[^0-9]", "", m.group(1))
            if digits:
                return int(digits)
    return 0


def _find_title(lines: list[str]) -> str:
    """El título es típicamente la primera línea no-tag-adornada.

    ML antepone "AUTO VERIFICADO" o similar como tag. Saltamos esas.
    """
    skip_prefixes = {"auto verificado", "envío gratis", "más vendido"}
    for line in lines:
        lc = line.lower()
        if any(lc.startswith(p) for p in skip_prefixes):
            continue
        if lc.startswith("$") or lc.endswith("km"):
            continue
        if _YEAR_RE.match(line):
            continue
        return line
    return lines[0] if lines else ""


def _find_location(lines: list[str]) -> str:
    """La ubicación suele ser la última línea con guión separando ciudad-estado."""
    for line in reversed(lines):
        if _LOCATION_RE.search(line) and not line.lower().endswith("km"):
            return line
    return ""


def _coerce_money(s: str | None) -> float:
    if not s:
        return 0.0
    cleaned = re.sub(r"[^0-9]", "", s)
    return float(cleaned) if cleaned else 0.0
