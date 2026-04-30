"""Smoke en vivo del estimador de precio.

Toma un listing simulado de Honda Civic 2018 80,000 km a $230,000 MXN,
trae comparables de ML Motors y devuelve PriceEstimate.
"""

import asyncio
import json
import sys

from app.analyzers.price_estimator import estimate
from app.models.report import ListingData, Source
from app.scrapers import ml_search


async def main() -> int:
    listing = ListingData(
        source=Source.MERCADOLIBRE,
        title="Honda Civic LX 2018 (smoke)",
        price_mxn=230_000,
        year=2018,
        make="Honda",
        model="Civic",
        kilometers=80_000,
        location="CDMX",
    )

    print(f"[smoke] Buscando comparables Honda Civic en ML Motors…", flush=True)
    comps = await ml_search.find_comparables("Honda", "Civic", limit=50)
    print(f"[smoke] Recolectados {len(comps)} comparables crudos", flush=True)
    if comps:
        sample = comps[:3]
        for c in sample:
            print(
                f"  {c.year} {c.title[:40]:40s} ${c.price_mxn:>10,.0f}  "
                f"{c.kilometers:>8,} km  {c.location[:25]}"
            )

    est = estimate(listing, comps, sources=["mercadolibre"])
    print(json.dumps(est.model_dump(mode="json"), indent=2, ensure_ascii=False))

    if est.fair_price_mxn is None or est.comparables_count == 0:
        print("[smoke] WARN: no se pudo estimar precio justo")
        return 1

    delta = est.delta_pct or 0.0
    veredicto = (
        "barato vs mercado" if delta < -10
        else "caro vs mercado" if delta > 10
        else "alineado con mercado"
    )
    print(
        f"[smoke] OK — anuncio ${listing.price_mxn:,.0f}, "
        f"fair ${est.fair_price_mxn:,.0f} "
        f"(delta {delta:+.1f}%, {est.comparables_count} comps): {veredicto}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
