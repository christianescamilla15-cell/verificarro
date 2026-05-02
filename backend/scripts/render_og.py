"""Render frontend/public/og-image.svg → og-image.png 1200×630.

Slack/FB crawlers viejos no parsean SVG; este script regenera el PNG
cuando el SVG cambia. Usa Playwright (ya instalado para REPUVE) para
renderizar el SVG vía headless Chromium.

Uso:

    cd backend && python scripts/render_og.py

Salida en `frontend/public/og-image.png`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
SVG_PATH = ROOT / "frontend" / "public" / "og-image.svg"
PNG_PATH = ROOT / "frontend" / "public" / "og-image.png"


async def main() -> None:
    svg = SVG_PATH.read_text(encoding="utf-8")
    html = (
        "<html><body style='margin:0;padding:0'>"
        f"{svg}"
        "</body></html>"
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(
            viewport={"width": 1200, "height": 630},
            device_scale_factor=1,
        )
        page = await ctx.new_page()
        await page.set_content(html)
        await page.locator("svg").screenshot(
            path=str(PNG_PATH), omit_background=False,
        )
        await browser.close()
    size_kb = PNG_PATH.stat().st_size / 1024
    print(f"OK · {PNG_PATH.relative_to(ROOT)} · {size_kb:.1f} KB")


if __name__ == "__main__":
    asyncio.run(main())
