"""Mercado Libre Motors scraper — D2.

Stub para D1. D2 implementa con Playwright:
- Navegar a la URL del anuncio
- Esperar selectores estables (precio, ficha técnica, fotos)
- Extraer: título, precio MXN, año, marca, modelo, kms, ubicación,
  descripción, vendedor, edad de cuenta, fotos
- Retornar `ListingData`
"""

from app.models.report import ListingData


async def scrape(url: str) -> ListingData:
    raise NotImplementedError("Mercado Libre Motors scraper se entrega en D2")
