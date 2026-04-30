"""Live network smoke test for the Mercado Libre Motors scraper.

Skipped by default. Activarlo con `RUN_LIVE_ML=1 pytest tests/test_mercadolibre_live.py`
o pasando `--run-live` (no implementado todavía).
"""

import os

import pytest

from app.scrapers.mercadolibre import scrape

LIVE_URL = os.getenv(
    "VERIFICARRO_LIVE_ML_URL",
    "https://autos.mercadolibre.com.mx/MLM-1234567890",  # placeholder
)


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_ML") != "1",
    reason="Live scrape disabled — set RUN_LIVE_ML=1 to enable",
)
async def test_live_ml_scrape() -> None:
    listing = await scrape(LIVE_URL)
    assert listing.title, "Title should not be empty"
    assert listing.price_mxn > 0, "Price should be > 0"
    assert listing.year >= 1990, "Year should be a sensible value"
    print("\n--- LIVE LISTING ---")
    print(listing.model_dump_json(indent=2))
