"""Smoke test: encuentra una URL real de ML Motors MX y la pasa por scrape().

Uso:
    python smoke_ml.py
"""

import asyncio
import json
import sys

from playwright.async_api import async_playwright

from app.scrapers.mercadolibre import _USER_AGENT, _is_valid_ml_url, scrape


async def find_first_listing() -> str | None:
    """Abre la página de autos y devuelve la primera URL de un anuncio."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
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
                "https://listado.mercadolibre.com.mx/autos",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            await page.wait_for_timeout(2_500)
            urls = await page.evaluate(
                """() => Array.from(document.querySelectorAll('a'))
                    .map(a => a.href)
                    .filter(h => h.includes('auto.mercadolibre.com.mx')
                              || h.includes('articulo.mercadolibre.com.mx'))
                """
            )
            for u in urls:
                clean = u.split("#")[0]
                if _is_valid_ml_url(clean):
                    return clean
        finally:
            await browser.close()
    return None


async def main() -> int:
    print("[smoke] Buscando una URL de auto en ML…", flush=True)
    url = await find_first_listing()
    if not url:
        print("[smoke] No encontré ninguna URL válida.", file=sys.stderr)
        return 1

    print(f"[smoke] URL: {url}", flush=True)
    print("[smoke] Scrapeando…", flush=True)
    listing = await scrape(url)
    print(json.dumps(listing.model_dump(mode="json"), indent=2, ensure_ascii=False))

    issues = []
    if not listing.title:
        issues.append("title vacío")
    if listing.price_mxn <= 0:
        issues.append("price_mxn <= 0")
    if listing.year < 1990:
        issues.append("year fuera de rango")
    if not listing.photo_urls:
        issues.append("no extrajo fotos")
    if issues:
        print("[smoke] FAIL:", "; ".join(issues), file=sys.stderr)
        return 1

    print(
        f"[smoke] OK — {listing.make} {listing.model} {listing.year}, "
        f"{listing.kilometers:,} km, ${listing.price_mxn:,.0f} MXN, "
        f"{len(listing.photo_urls)} fotos",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
