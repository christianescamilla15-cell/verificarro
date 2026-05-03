"""Endpoint para recibir resultados de REPUVE scrapeados por la
extension de Chrome del usuario.

La extension `verificarro-helper` corre en el navegador del usuario
(IP residencial MX, cookies Google reales, fingerprint humano), abre
una pestana invisible a `repuve.gob.mx`, captura el HTML del modal de
resultado y lo manda aqui. Este endpoint solo parsea — no scrapea.

## Por que asi

El sidecar Vultr CDMX con stealth+rebrowser-playwright dio 0/67 hit
rate sobre 3 configs A/B (sesion 2026-05-03). reCaptcha v3 penaliza
~25% del score por IP datacenter, no compensable con stealth. Mover
la consulta al browser del usuario elimina ese factor — score sube a
~0.7-0.9 baseline y el captcha invisible no dispara challenge.

## Auth

Sin JWT obligatorio: el flow de scan ya esta detras de rate limit por
IP, y un anon que tenga la extension instalada y mande HTML valido
recibe un parse igual que cualquier otro. El user reusa la consulta
en el flow normal de `POST /api/scan/plate` o `/api/analyze`.

## Limites

- HTML max 200 KB (modal REPUVE real ronda <50 KB, margen 4x).
- Rate limit 30/min, 200/hora por IP — mismo orden que `/scan/plate`.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.models.report import RepuveResult
from app.rate_limit import limiter
from app.scrapers.repuve import parse_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repuve", tags=["repuve-extension"])

_MAX_HTML_BYTES = 200_000


class ExtensionResultRequest(BaseModel):
    """Body de `POST /api/repuve/extension-result`."""

    plate: str | None = Field(default=None, max_length=16)
    vin: str | None = Field(default=None, max_length=24)
    html: str = Field(
        min_length=1,
        description="HTML del modal de resultado de REPUVE capturado por la extension",
    )
    source: str = Field(
        default="extension",
        max_length=64,
        description="Identifica origen + version del client (e.g. 'extension/0.1.0')",
    )


class ExtensionResultResponse(BaseModel):
    queried: bool
    plate: str | None = None
    vin: str | None = None
    is_stolen: bool | None = None
    has_legal_status: bool | None = None
    raw_status: str | None = None
    error: str | None = None
    parser: Literal["html_modal"] = "html_modal"


@router.post("/extension-result", response_model=ExtensionResultResponse)
@limiter.limit("30/minute;200/hour")
async def extension_result(
    request: Request,
    body: ExtensionResultRequest,
) -> ExtensionResultResponse:
    if not body.plate and not body.vin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Falta placa o NIV",
        )
    html_bytes = len(body.html.encode("utf-8"))
    if html_bytes > _MAX_HTML_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"HTML excede limite ({html_bytes} > {_MAX_HTML_BYTES} bytes)",
        )

    logger.info(
        "extension_result source=%s plate=%s vin=%s html_bytes=%d",
        body.source, body.plate, body.vin, html_bytes,
    )

    result: RepuveResult = parse_response(
        body.html,
        plate=body.plate,
        vin=body.vin,
        captcha_used=False,
    )

    return ExtensionResultResponse(
        queried=result.queried,
        plate=result.plate,
        vin=result.vin,
        is_stolen=result.is_stolen,
        has_legal_status=result.has_legal_status,
        raw_status=result.raw_status,
        error=result.error,
    )
