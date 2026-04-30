"""Recon: explora el portal de REPUVE para ver layout, selectores y captcha actuales.

Solo navegación, sin envío de formulario. Guarda HTML + screenshot en /tmp.
"""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

REPUVE_URLS = [
    "https://www2.repuve.gob.mx:8443/ciudadania/consulta",
    "https://www2.repuve.gob.mx:8443/ciudadania/",
]


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=UA,
                locale="es-MX",
                viewport={"width": 1280, "height": 900},
                ignore_https_errors=True,
            )
            page = await context.new_page()
            for url in REPUVE_URLS:
                print(f"\n=== Probing {url} ===")
                try:
                    response = await page.goto(
                        url, wait_until="networkidle", timeout=45_000
                    )
                    status = response.status if response else "no-response"
                    print(f"HTTP status: {status}")
                    await page.wait_for_timeout(2_500)
                    print(f"Final URL:   {page.url}")
                    print(f"Title:       {await page.title()}")
                    html = await page.content()
                    print(f"HTML size:   {len(html)} chars")

                    # Look for likely form / captcha elements
                    indicators = {
                        "input[name*='placa']": "placa input",
                        "input[name*='niv']": "NIV input",
                        "input[name*='captcha']": "captcha input",
                        "img[src*='captcha']": "captcha image (src)",
                        "img[id*='captcha']": "captcha image (id)",
                        "button[type='submit']": "submit button",
                        "form": "any <form>",
                    }
                    for sel, label in indicators.items():
                        count = await page.locator(sel).count()
                        if count:
                            print(f"  found {count} × {label} ({sel})")
                    safe = url.replace(":", "_").replace("/", "_")
                    Path(f"recon_{safe}.html").write_text(html, encoding="utf-8")
                    await page.screenshot(path=f"recon_{safe}.png", full_page=True)
                    print(f"  saved recon_{safe}.html + .png")
                except Exception as exc:  # noqa: BLE001
                    print(f"  ERROR: {exc}")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
