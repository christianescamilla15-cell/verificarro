"""Sidecar service `verificarro-scraper-mx` — entrypoint alternativo.

NO es la app principal. Esta app micro expone UN solo endpoint
(`POST /scrape/repuve`) y se deploya en un host con IP mexicana
(Vultr CDMX, Hostinger MX, etc.) para evitar el WAF de gob.mx que
bloquea IPs no-mexicanas.

El backend principal (en Render Oregon) llama a este sidecar via
HTTP cuando `REPUVE_SCRAPER_URL` está configurado. La sidecar reusa
el mismo `app/scrapers/repuve.py` que la app principal — zero
duplicación de código del scraper / captcha bypass / stealth.

## Auth

Bearer token compartido vía `REPUVE_SCRAPER_TOKEN` (mismo valor en
backend principal y sidecar). Sin esto, cualquiera con la URL del
sidecar podría drenar tus créditos de 2Captcha.

## Deploy

Mismo Dockerfile que el backend principal pero con CMD distinto.
Ver `scraper-mx.Dockerfile` en repo root.

## Health

`GET /health` responde sin auth para que el orquestador checkée vivacidad.
El endpoint de scrape SÍ requiere auth.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.scrapers.repuve import query as repuve_query

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Reusamos el bootstrap defensivo del backend principal —
    # garantiza Chromium en runtime aunque el deploy se haya saltado
    # `playwright install chromium`.
    try:
        from app.services.playwright_bootstrap import (
            ensure_chromium_installed,
        )
        await ensure_chromium_installed()
    except Exception:  # noqa: BLE001
        logger.exception("Playwright bootstrap falló en sidecar (no-bloqueante)")
    yield


app = FastAPI(
    title="Verificarro Scraper MX",
    description="Sidecar microservice — REPUVE scrape desde IP mexicana",
    version="0.1.0",
    lifespan=lifespan,
)


class ScrapeRequest(BaseModel):
    """Body de `POST /scrape/repuve`.

    Mismo input que la query() local del backend: una de las dos
    debe venir set.
    """
    plate: str | None = Field(default=None, max_length=16)
    vin: str | None = Field(default=None, max_length=24)


class ScrapeResponse(BaseModel):
    """Serialización de RepuveResult — mismo shape para que el caller
    pueda parsear directo a su modelo Pydantic."""
    queried: bool
    plate: str | None = None
    vin: str | None = None
    is_stolen: bool | None = None
    has_legal_status: bool | None = None
    raw_status: str | None = None
    error: str | None = None


def _check_token(authorization: str | None) -> None:
    """Valida Bearer token contra REPUVE_SCRAPER_TOKEN env var.

    Si la env var NO está set, rechazamos TODAS las requests (fail-closed)
    — un sidecar sin auth es un open proxy para drenar 2Captcha.
    """
    expected = os.environ.get("REPUVE_SCRAPER_TOKEN", "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="REPUVE_SCRAPER_TOKEN no configurado en sidecar",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta Authorization Bearer header",
        )
    provided = authorization.split(" ", 1)[1].strip()
    # Comparison constant-time vía hmac no es crítico aquí (token compartido,
    # no PII), pero costo cero hacerlo bien.
    import hmac
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token inválido",
        )


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe — sin auth para orquestador (Docker, k8s, Vultr health)."""
    return {"status": "ok", "service": "verificarro-scraper-mx"}


@app.post("/scrape/repuve", response_model=ScrapeResponse)
async def scrape_repuve(
    body: ScrapeRequest,
    authorization: str | None = Header(default=None),
) -> ScrapeResponse:
    """Ejecuta query() de REPUVE en este host (presumiblemente IP MX)
    y devuelve el RepuveResult serializado."""
    _check_token(authorization)

    if not body.plate and not body.vin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Necesitas plate o vin",
        )

    result = await repuve_query(plate=body.plate, vin=body.vin)
    return ScrapeResponse(
        queried=result.queried,
        plate=result.plate,
        vin=result.vin,
        is_stolen=result.is_stolen,
        has_legal_status=result.has_legal_status,
        raw_status=result.raw_status,
        error=result.error,
    )
