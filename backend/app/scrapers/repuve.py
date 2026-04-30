"""REPUVE scraper — D3.

REPUVE (gob.mx) no expone API oficial. Consulta es información pública
pero con captcha que rota cada tanto. D3 implementa Playwright headed
con resolución manual de captcha en sandbox controlado.

Throttle: 1 req/seg por respeto al portal.
"""

from app.models.report import RepuveResult


async def query(plate: str | None = None, vin: str | None = None) -> RepuveResult:
    raise NotImplementedError("REPUVE scraper se entrega en D3")
